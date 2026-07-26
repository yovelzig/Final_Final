"""Domain models for the provider-neutral Live Research domain (Phase G1).

This module has no knowledge of any infrastructure (databases, queues,
Celery, Redis, HTTP frameworks, orchestration engines, etc.) or any
provider (Perplexity, SEC EDGAR, yfinance, OpenAI, ...) - the same rule
every other `domain/*` package follows.

G1 defines the domain contract only: no provider call, no HTTP fetch, no
job-queue enqueue happens anywhere in this package.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import ConfigDict, Field, HttpUrl, field_validator, model_validator

from stock_research_core.domain.live_research.enums import (
    TERMINAL_RESEARCH_RUN_STATUSES,
    ClaimCategory,
    ClaimStatus,
    EvidenceClassification,
    EvidenceStance,
    FailureCategory,
    ResearchRunStatus,
    ResearchScope,
    SourceType,
)
from stock_research_core.domain.models import DomainModel, utc_now
from stock_research_core.domain.operations.sanitization import (
    contains_credential_leak,
    contains_traceback,
    find_sensitive_keys,
)

_HEX_DIGITS = frozenset("0123456789abcdef")


def _validate_sha256_hex(value: str, *, field_name: str) -> str:
    if len(value) != 64 or any(ch not in _HEX_DIGITS for ch in value):
        raise ValueError(f"{field_name} must be a lowercase 64-character hex SHA-256 digest")
    return value


def _reject_sensitive_mapping(data: dict[str, Any] | None, *, field_name: str) -> None:
    if data is None:
        return
    sensitive_paths = find_sensitive_keys(data)
    if sensitive_paths:
        raise ValueError(f"{field_name} must not contain sensitive fields (found: {', '.join(sensitive_paths)})")
    if contains_traceback(data):
        raise ValueError(f"{field_name} must not contain a raw traceback")


def _is_blank(value: str | None) -> bool:
    return value is None or value.strip() == ""


def _is_empty_mapping(value: dict[str, Any] | None) -> bool:
    return value is None or len(value) == 0


class ResearchRequest(DomainModel):
    """A single research question, normalized and idempotency-scoped.

    `normalized_query` and `request_hash` are always derived by the
    application service (never taken verbatim from an external caller) -
    see `stock_research_core.domain.live_research.hashing`.
    """

    request_id: UUID = Field(default_factory=uuid4)

    requested_by_account_id: UUID | None = None
    requested_by_integration_id: UUID | None = None

    original_question: str = Field(min_length=3, max_length=5000)
    normalized_query: str = Field(min_length=1, max_length=2000)

    subject_security_id: UUID | None = None
    subject_raw_text: str | None = Field(default=None, max_length=250)

    scope: ResearchScope

    idempotency_key: str = Field(min_length=1, max_length=200)
    request_hash: str = Field(min_length=64, max_length=64)

    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("request_hash")
    @classmethod
    def _validate_request_hash(cls, value: str) -> str:
        return _validate_sha256_hex(value, field_name="request_hash")

    @model_validator(mode="after")
    def _validate_requester_identity(self) -> ResearchRequest:
        has_account = self.requested_by_account_id is not None
        has_integration = self.requested_by_integration_id is not None
        if has_account == has_integration:
            raise ValueError(
                "exactly one of requested_by_account_id or requested_by_integration_id must be set"
            )
        return self

    @model_validator(mode="after")
    def _validate_subject(self) -> ResearchRequest:
        has_security = self.subject_security_id is not None
        has_raw_text = not _is_blank(self.subject_raw_text)
        if has_security and has_raw_text:
            raise ValueError("subject_security_id and subject_raw_text must not both be set")
        if not has_security and not has_raw_text and self.scope != ResearchScope.GENERAL_QUESTION:
            raise ValueError(
                "a subject (subject_security_id or subject_raw_text) is required unless scope is GENERAL_QUESTION"
            )
        return self


class ResearchRun(DomainModel):
    """One execution attempt at answering a `ResearchRequest`.

    `attempt_number` starts at 1 for a request's first run; a retry after
    FAILED always creates a *new* `ResearchRun` row with the next integer,
    never a reactivation of this one. COMPLETED, FAILED, and CANCELLED are
    all strictly terminal - no row in any terminal status ever transitions
    again.
    """

    run_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    attempt_number: int = Field(ge=1)

    status: ResearchRunStatus = ResearchRunStatus.QUEUED

    failure_category: FailureCategory | None = None
    failure_message: str | None = Field(default=None, max_length=2000)
    retryable: bool | None = None

    provider_metadata: dict[str, Any] = Field(default_factory=dict)

    queued_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None

    @field_validator("provider_metadata")
    @classmethod
    def _validate_provider_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_sensitive_mapping(value, field_name="provider_metadata")
        return value

    @field_validator("failure_message")
    @classmethod
    def _validate_failure_message(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if contains_traceback(value):
            raise ValueError("failure_message must not contain a raw traceback")
        if contains_credential_leak(value):
            raise ValueError("failure_message must not contain credential-shaped content")
        return value

    @model_validator(mode="after")
    def _validate_lifecycle_timestamps(self) -> ResearchRun:
        if self.status == ResearchRunStatus.RUNNING and self.started_at is None:
            raise ValueError("a RUNNING run requires started_at")
        if self.status in TERMINAL_RESEARCH_RUN_STATUSES:
            if self.status == ResearchRunStatus.CANCELLED:
                if self.completed_at is None and self.cancelled_at is None:
                    raise ValueError("a CANCELLED run requires completed_at or cancelled_at")
            elif self.completed_at is None:
                raise ValueError(f"a {self.status.value} run requires completed_at")
        return self

    @model_validator(mode="after")
    def _validate_failure_fields(self) -> ResearchRun:
        if self.status == ResearchRunStatus.FAILED:
            if self.failure_category is None or self.retryable is None or _is_blank(self.failure_message):
                raise ValueError(
                    "a FAILED run requires failure_category, a non-blank failure_message, and retryable"
                )
        return self


class EvidenceItem(DomainModel):
    """An immutable, provenance-carrying record of one piece of evidence
    gathered for a `ResearchRun`.

    Source-identity invariant: at least one of `source_url` /
    `official_identifier` must be present - both may be present
    simultaneously (e.g. an SEC filing with both a URL and an accession
    number); only "neither" is invalid.

    Payload-completeness invariant: at least one of `raw_excerpt` /
    `structured_facts` must carry meaningful (non-null, non-blank,
    non-empty) content - both may be present simultaneously; only "both
    missing/blank/empty" is invalid.

    `content_hash` is the SHA-256 of the canonical *persisted* payload -
    see `stock_research_core.domain.live_research.hashing`. This model
    validates only its format; computing it is the caller's
    responsibility, using the one shared canonicalization function.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        protected_namespaces=(),
        frozen=True,
    )

    evidence_id: UUID = Field(default_factory=uuid4)
    run_id: UUID

    source_type: SourceType
    classification: EvidenceClassification

    source_url: HttpUrl | None = None
    official_identifier: str | None = Field(default=None, max_length=200)

    source_title: str = Field(min_length=1, max_length=1000)
    publisher: str = Field(min_length=1, max_length=250)

    retrieved_at: datetime = Field(default_factory=utc_now)
    published_at: datetime | None = None

    raw_excerpt: str | None = Field(default=None, max_length=5000)
    normalized_text: str | None = Field(default=None, max_length=5000)

    content_hash: str = Field(min_length=64, max_length=64)

    structured_facts: dict[str, Any] | None = None

    @field_validator("content_hash")
    @classmethod
    def _validate_content_hash(cls, value: str) -> str:
        return _validate_sha256_hex(value, field_name="content_hash")

    @field_validator("structured_facts")
    @classmethod
    def _validate_structured_facts(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return value
        _reject_sensitive_mapping(value, field_name="structured_facts")
        return value

    @field_validator("raw_excerpt")
    @classmethod
    def _validate_raw_excerpt(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if contains_traceback(value) or contains_credential_leak(value):
            raise ValueError("raw_excerpt must not contain a traceback or credential-shaped content")
        return value

    @model_validator(mode="after")
    def _validate_source_identity(self) -> EvidenceItem:
        if self.source_url is None and _is_blank(self.official_identifier):
            raise ValueError(
                "at least one of source_url or official_identifier must be present "
                "(both may be present simultaneously)"
            )
        return self

    @model_validator(mode="after")
    def _validate_payload_completeness(self) -> EvidenceItem:
        has_excerpt = not _is_blank(self.raw_excerpt)
        has_structured_facts = not _is_empty_mapping(self.structured_facts)
        if not has_excerpt and not has_structured_facts:
            raise ValueError(
                "at least one of raw_excerpt or structured_facts must contain meaningful evidence "
                "(both may be present simultaneously); null, blank, and empty values all count as missing"
            )
        return self


class ResearchClaim(DomainModel):
    """A single normalized claim derived from a `ResearchRun`'s evidence.

    Carries only its own scalar data - no evidence-ID lists. The
    claim<->evidence relationship is persisted exclusively via
    `ClaimEvidenceLink`; consistency rules that depend on evidence (e.g.
    CORROBORATED requires a supporting link) are enforced by the
    application service, which reads `ClaimEvidenceLink` rows - the
    domain model here has no visibility into sibling link rows.
    """

    claim_id: UUID = Field(default_factory=uuid4)
    run_id: UUID

    claim_text: str = Field(min_length=1, max_length=2000)
    category: ClaimCategory
    status: ClaimStatus = ClaimStatus.UNVERIFIED
    confidence_score: float | None = Field(default=None, ge=0, le=1)

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_unverified_has_no_confidence(self) -> ResearchClaim:
        if self.status == ClaimStatus.UNVERIFIED and self.confidence_score is not None:
            raise ValueError("an UNVERIFIED claim must not carry a confidence_score")
        return self


class ClaimEvidenceLink(DomainModel):
    """The sole persisted record of a claim<->evidence relationship.

    One row per `(claim_id, evidence_id)` pair (DB-unique) - a stance,
    once recorded, is not changed in place in G1; there is no update path
    defined for it here.
    """

    link_id: UUID = Field(default_factory=uuid4)
    claim_id: UUID
    evidence_id: UUID
    stance: EvidenceStance

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
