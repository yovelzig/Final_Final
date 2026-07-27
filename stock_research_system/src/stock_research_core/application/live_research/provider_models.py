"""Application-level provider-neutral request/result models for Live
Research infrastructure adapters (Phase G2A1).

These models sit at the boundary between an external provider (Perplexity
Search, SEC EDGAR, ...) and the provider-neutral G1 domain
(`domain.live_research`). No httpx, provider name, environment variable,
or network behavior is imported here - only Pydantic validation. G2A1
never persists an `ExternalEvidenceCandidate`; converting one into a
`ResearchRequestService.record_evidence(...)` call is left to a later
orchestration phase.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from stock_research_core.domain.live_research.enums import EvidenceClassification, SourceType
from stock_research_core.domain.models import DomainModel, utc_now
from stock_research_core.domain.operations.sanitization import contains_credential_leak, contains_traceback, find_sensitive_keys

_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})
_ISO_ALPHA2_PATTERN = re.compile(r"^[A-Za-z]{2}$")

_MAX_DOMAIN_FILTER_LENGTH = 253
_MAX_CONCEPTS = 50
_MAX_RAW_LIST_LENGTH = 200  # bounds arbitrary-length input before dedup/validation


def _is_blank(value: str | None) -> bool:
    return value is None or value.strip() == ""


def _is_empty_mapping(value: dict[str, Any] | None) -> bool:
    return value is None or len(value) == 0


def _reject_sensitive_mapping(data: dict[str, Any] | None, *, field_name: str) -> None:
    if data is None:
        return
    sensitive_paths = find_sensitive_keys(data)
    if sensitive_paths:
        raise ValueError(f"{field_name} must not contain sensitive fields (found: {', '.join(sensitive_paths)})")
    if contains_traceback(data):
        raise ValueError(f"{field_name} must not contain a raw traceback")


def _reject_duplicates(items: list[str], *, field_name: str) -> None:
    seen: set[str] = set()
    for item in items:
        if item in seen:
            raise ValueError(f"{field_name} contains duplicate entries after normalization: {item!r}")
        seen.add(item)


def _validate_iso_alpha2(value: str, *, field_name: str) -> str:
    if not _ISO_ALPHA2_PATTERN.match(value.strip()):
        raise ValueError(f"{field_name} must be a 2-letter ISO alpha-2 code")
    return value.strip()


_CIK_PATTERN = re.compile(r"^[0-9]{1,10}$")


def _normalize_cik(value: str) -> str:
    stripped = value.strip()
    if not _CIK_PATTERN.match(stripped):
        raise ValueError("cik must match ^[0-9]{1,10}$ (ASCII digits only)")
    if int(stripped) == 0:
        raise ValueError("cik must not be all-zero")
    return stripped.zfill(10)


def _normalize_forms(value: list[str]) -> list[str]:
    if len(value) > _MAX_RAW_LIST_LENGTH:
        raise ValueError(f"forms must not exceed {_MAX_RAW_LIST_LENGTH} raw entries")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        stripped = item.strip().upper()
        if not stripped:
            raise ValueError("forms entries must not be blank")
        if len(stripped) > 20:
            raise ValueError("each forms entry must be at most 20 characters")
        if stripped not in seen:
            seen.add(stripped)
            normalized.append(stripped)
    return normalized


class ExternalEvidenceCandidate(DomainModel):
    """A single piece of provider-sourced evidence, not yet persisted.

    Field bounds mirror `domain.live_research.models.EvidenceItem` exactly
    so a later phase can convert an accepted candidate into a
    `ResearchRequestService.record_evidence(...)` call without silently
    truncating or re-validating data a second time.
    """

    source_type: SourceType
    classification: EvidenceClassification

    source_url: str | None = Field(default=None, max_length=2000)
    official_identifier: str | None = Field(default=None, max_length=200)

    source_title: str = Field(min_length=1, max_length=1000)
    publisher: str = Field(min_length=1, max_length=250)

    published_at: datetime | None = None

    raw_excerpt: str | None = Field(default=None, max_length=5000)
    normalized_text: str | None = Field(default=None, max_length=5000)

    structured_facts: dict[str, Any] | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_url")
    @classmethod
    def _validate_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES or not parsed.netloc:
            raise ValueError("source_url must use http:// or https:// and include a host")
        return value

    @field_validator("raw_excerpt")
    @classmethod
    def _validate_raw_excerpt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if contains_traceback(value) or contains_credential_leak(value):
            raise ValueError("raw_excerpt must not contain a traceback or credential-shaped content")
        return value

    @field_validator("structured_facts")
    @classmethod
    def _validate_structured_facts(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        _reject_sensitive_mapping(value, field_name="structured_facts")
        return value

    @field_validator("provider_metadata")
    @classmethod
    def _validate_provider_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_sensitive_mapping(value, field_name="provider_metadata")
        return value

    @model_validator(mode="after")
    def _validate_source_identity(self) -> ExternalEvidenceCandidate:
        if self.source_url is None and _is_blank(self.official_identifier):
            raise ValueError("at least one of source_url or official_identifier must be present")
        return self

    @model_validator(mode="after")
    def _validate_payload_completeness(self) -> ExternalEvidenceCandidate:
        has_excerpt = not _is_blank(self.raw_excerpt)
        has_structured_facts = not _is_empty_mapping(self.structured_facts)
        if not has_excerpt and not has_structured_facts:
            raise ValueError("at least one of raw_excerpt or structured_facts must contain meaningful evidence")
        return self


class ProviderFetchResult(DomainModel):
    """One provider call's raw, ordered result batch.

    `candidates` preserves the provider's own ranking/ordering; nothing in
    this model infers truth, ranks by trustworthiness, or synthesizes a
    claim from the batch.
    """

    provider_name: str = Field(min_length=1, max_length=100)
    provider_request_id: str | None = Field(default=None, max_length=200)
    fetched_at: datetime = Field(default_factory=utc_now)
    candidates: list[ExternalEvidenceCandidate] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_sensitive_mapping(value, field_name="metadata")
        return value


class DiscoveryRecency(StrEnum):
    """Perplexity Search's closed `search_recency_filter` values."""

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class DiscoverySearchRequest(DomainModel):
    """A discovery-only Perplexity Search request. Carries no Sonar/Agent
    API concept (model, messages, temperature, ...) - only the fields
    Perplexity's `/search` endpoint itself accepts."""

    query: str = Field(min_length=1, max_length=2000)
    max_results: int = Field(default=10, ge=1, le=20)
    country: str | None = None
    language_filters: list[str] = Field(default_factory=list, max_length=10)
    domain_filters: list[str] = Field(default_factory=list, max_length=20)
    recency: DiscoveryRecency | None = None

    @field_validator("query")
    @classmethod
    def _validate_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be blank")
        return stripped

    @field_validator("country")
    @classmethod
    def _validate_country(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_iso_alpha2(value, field_name="country").upper()

    @field_validator("language_filters")
    @classmethod
    def _validate_language_filters(cls, value: list[str]) -> list[str]:
        normalized = [_validate_iso_alpha2(item, field_name="language_filters entry").lower() for item in value]
        _reject_duplicates(normalized, field_name="language_filters")
        return normalized

    @field_validator("domain_filters")
    @classmethod
    def _validate_domain_filters(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            stripped = item.strip()
            if not stripped or len(stripped) > _MAX_DOMAIN_FILTER_LENGTH:
                raise ValueError(f"domain_filters entries must be 1-{_MAX_DOMAIN_FILTER_LENGTH} characters")
            normalized.append(stripped.lower())
        _reject_duplicates(normalized, field_name="domain_filters")
        return normalized

    @model_validator(mode="after")
    def _validate_domain_filter_polarity(self) -> DiscoverySearchRequest:
        has_allow = any(not entry.startswith("-") for entry in self.domain_filters)
        has_deny = any(entry.startswith("-") for entry in self.domain_filters)
        if has_allow and has_deny:
            raise ValueError(
                "domain_filters must not mix allowlist entries and denylist ('-'-prefixed) entries"
            )
        return self


class SecSubmissionsRequest(DomainModel):
    """A request for one company's SEC EDGAR `submissions` document."""

    cik: str
    forms: list[str] | None = None
    limit: int = Field(default=100, ge=1, le=200)

    @field_validator("cik")
    @classmethod
    def _validate_cik(cls, value: str) -> str:
        return _normalize_cik(value)

    @field_validator("forms")
    @classmethod
    def _validate_forms(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _normalize_forms(value)


_DEFAULT_SEC_COMPANY_FACTS_FORMS: tuple[str, ...] = ("10-K", "10-Q")
_DEFAULT_SEC_TAXONOMY = "us-gaap"


class SecCompanyFactsRequest(DomainModel):
    """A request for a bounded slice of one company's SEC EDGAR
    `companyfacts` document - specific taxonomy/concepts only, never the
    entire unbounded payload."""

    cik: str
    taxonomy: str = Field(default=_DEFAULT_SEC_TAXONOMY, min_length=1, max_length=100)
    concepts: list[str]
    forms: list[str] = Field(default_factory=lambda: list(_DEFAULT_SEC_COMPANY_FACTS_FORMS))
    max_facts_per_concept: int = Field(default=20, ge=1, le=100)

    @field_validator("cik")
    @classmethod
    def _validate_cik(cls, value: str) -> str:
        return _normalize_cik(value)

    @field_validator("taxonomy")
    @classmethod
    def _validate_taxonomy(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("taxonomy must not be blank")
        return stripped

    @field_validator("concepts")
    @classmethod
    def _validate_concepts(cls, value: list[str]) -> list[str]:
        if len(value) > _MAX_RAW_LIST_LENGTH:
            raise ValueError(f"concepts must not exceed {_MAX_RAW_LIST_LENGTH} raw entries")
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            stripped = item.strip()
            if not stripped:
                raise ValueError("concepts entries must not be blank")
            if len(stripped) > 200:
                raise ValueError("each concept must be at most 200 characters")
            if stripped not in seen:
                seen.add(stripped)
                normalized.append(stripped)
        if not normalized:
            raise ValueError("concepts must contain at least one entry")
        if len(normalized) > _MAX_CONCEPTS:
            raise ValueError(f"concepts must not exceed {_MAX_CONCEPTS} entries after deduplication")
        return normalized

    @field_validator("forms")
    @classmethod
    def _validate_forms(cls, value: list[str]) -> list[str]:
        return _normalize_forms(value)
