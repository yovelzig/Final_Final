"""Canonical, deterministic hashing of a persisted `EvidenceItem` payload
(Phase G1, Live Research domain).

`compute_evidence_content_hash` is the single shared implementation used
identically by the domain model's own field default, the application
service, and any repository-level verification - it must never be
re-implemented per layer.

The hash covers only fields FinQuest actually persists on `EvidenceItem`.
It deliberately excludes `evidence_id`, `run_id`, `retrieved_at` (a
fetch-time timestamp, not source content), and any transient
provider-specific metadata - none of those are passed in here at all.
A later phase's concept of hashing a complete raw source artifact stored
in an object store (S3) is a separate, later field - it must not be
folded into this hash.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID


def _canonical_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("datetime values passed to canonical evidence hashing must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_text(value: str | None) -> str | None:
    """Normalize line endings to LF so CRLF and LF input canonicalize identically."""
    if value is None:
        return None
    return value.replace("\r\n", "\n").replace("\r", "\n")


def canonical_evidence_payload(
    *,
    source_type: str,
    classification: str,
    source_url: str | None,
    official_identifier: str | None,
    source_title: str,
    publisher: str,
    published_at: datetime | None,
    raw_excerpt: str | None,
    normalized_text: str | None,
    structured_facts: dict[str, Any] | None,
) -> str:
    """The exact canonical UTF-8 string that `compute_evidence_content_hash`
    hashes: a fixed, explicit field order; `None` always serializes as
    JSON `null`; nested mapping keys are sorted recursively; no
    insignificant whitespace; datetimes are UTC ISO-8601 (`...Z`).
    """
    envelope = {
        "source_type": source_type,
        "classification": classification,
        "source_url": source_url,
        "official_identifier": official_identifier,
        "source_title": source_title,
        "publisher": publisher,
        "published_at": _canonical_datetime(published_at),
        "raw_excerpt": _canonical_text(raw_excerpt),
        "normalized_text": _canonical_text(normalized_text),
        "structured_facts": structured_facts,
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_evidence_content_hash(
    *,
    source_type: str,
    classification: str,
    source_url: str | None,
    official_identifier: str | None,
    source_title: str,
    publisher: str,
    published_at: datetime | None,
    raw_excerpt: str | None,
    normalized_text: str | None,
    structured_facts: dict[str, Any] | None,
) -> str:
    """SHA-256 (lowercase hex, 64 characters) of the canonical persisted
    evidence payload. The same persisted payload always produces the same
    hash, regardless of `structured_facts` key insertion order, input
    CRLF/LF differences, or the calling machine's locale/timezone.
    """
    payload = canonical_evidence_payload(
        source_type=source_type,
        classification=classification,
        source_url=source_url,
        official_identifier=official_identifier,
        source_title=source_title,
        publisher=publisher,
        published_at=published_at,
        raw_excerpt=raw_excerpt,
        normalized_text=normalized_text,
        structured_facts=structured_facts,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_query(original_question: str) -> str:
    """Lowercased, whitespace-collapsed form of a research question. Used
    for idempotency comparison and as an input to `compute_request_hash`.
    """
    return _WHITESPACE_RUN.sub(" ", original_question.strip().lower())


def canonical_request_payload(
    *,
    normalized_query: str,
    scope: str,
    subject_security_id: UUID | None,
    subject_raw_text: str | None,
) -> str:
    """The exact canonical UTF-8 string that `compute_request_hash` hashes.
    Mirrors `canonical_evidence_payload`'s determinism rules."""
    envelope = {
        "normalized_query": normalized_query,
        "scope": scope,
        "subject_security_id": str(subject_security_id) if subject_security_id is not None else None,
        "subject_raw_text": _canonical_text(subject_raw_text),
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_request_hash(
    *,
    normalized_query: str,
    scope: str,
    subject_security_id: UUID | None,
    subject_raw_text: str | None,
) -> str:
    """SHA-256 (lowercase hex, 64 characters) of the canonical
    `ResearchRequest` identity payload - the same requester + idempotency
    key with a different `request_hash` indicates a conflicting reuse of
    that key (see `ResearchRequestConflictError`)."""
    payload = canonical_request_payload(
        normalized_query=normalized_query, scope=scope,
        subject_security_id=subject_security_id, subject_raw_text=subject_raw_text,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def requester_key(*, account_id: UUID | None, integration_id: UUID | None) -> str:
    """The same `account:{id}` / `integration:{id}` convention used by
    `BackgroundJobORM.requester_key` (`infrastructure/database/repositories/background_job_repository.py`),
    reused here for `ResearchRequest`'s idempotency scope."""
    if account_id is not None:
        return f"account:{account_id}"
    if integration_id is not None:
        return f"integration:{integration_id}"
    raise ValueError("exactly one of account_id or integration_id must be set to derive a requester_key")
