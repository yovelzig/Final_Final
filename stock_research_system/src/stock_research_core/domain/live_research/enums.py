"""Enumerations for the provider-neutral Live Research domain (Phase G1).

This module has no knowledge of any provider (Perplexity, SEC EDGAR,
yfinance, OpenAI, ...) or infrastructure (databases, queues, HTTP
frameworks, orchestration engines, etc.).
"""

from enum import StrEnum


class ResearchRunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


#: Statuses from which a `ResearchRun` will never transition again. A
#: retry after FAILED always creates a *new* `ResearchRun` row (with the
#: next `attempt_number`) rather than reactivating this one.
TERMINAL_RESEARCH_RUN_STATUSES: frozenset[ResearchRunStatus] = frozenset(
    {
        ResearchRunStatus.COMPLETED,
        ResearchRunStatus.FAILED,
        ResearchRunStatus.CANCELLED,
    }
)


class ResearchScope(StrEnum):
    COMPANY_OVERVIEW = "COMPANY_OVERVIEW"
    FINANCIAL_FILING_REVIEW = "FINANCIAL_FILING_REVIEW"
    NEWS_SCAN = "NEWS_SCAN"
    ANALYST_SENTIMENT = "ANALYST_SENTIMENT"
    MARKET_DATA_SNAPSHOT = "MARKET_DATA_SNAPSHOT"
    GENERAL_QUESTION = "GENERAL_QUESTION"


class SourceType(StrEnum):
    SEC_OFFICIAL_FILING = "SEC_OFFICIAL_FILING"
    COMPANY_INVESTOR_RELATIONS = "COMPANY_INVESTOR_RELATIONS"
    EXCHANGE_REGULATOR_GOVERNMENT = "EXCHANGE_REGULATOR_GOVERNMENT"
    STRUCTURED_MARKET_DATA_PROVIDER = "STRUCTURED_MARKET_DATA_PROVIDER"
    REPUTABLE_SECONDARY_SOURCE = "REPUTABLE_SECONDARY_SOURCE"
    DISCOVERY_ONLY = "DISCOVERY_ONLY"
    UNKNOWN_UNVERIFIED = "UNKNOWN_UNVERIFIED"


class EvidenceClassification(StrEnum):
    OFFICIAL = "OFFICIAL"
    NON_OFFICIAL = "NON_OFFICIAL"


class ClaimCategory(StrEnum):
    FINANCIAL_METRIC = "FINANCIAL_METRIC"
    GUIDANCE_STATEMENT = "GUIDANCE_STATEMENT"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    REGULATORY_STATUS = "REGULATORY_STATUS"
    MARKET_SENTIMENT = "MARKET_SENTIMENT"
    ANALYST_OPINION = "ANALYST_OPINION"
    GENERAL_FACT = "GENERAL_FACT"


class ClaimStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    CORROBORATED = "CORROBORATED"
    CONTESTED = "CONTESTED"
    UNRESOLVED_CONFLICT = "UNRESOLVED_CONFLICT"
    RETRACTED = "RETRACTED"


class EvidenceStance(StrEnum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    NEUTRAL_INSUFFICIENT = "NEUTRAL_INSUFFICIENT"


class FailureCategory(StrEnum):
    PROVIDER_ERROR = "PROVIDER_ERROR"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    INVALID_SCOPE = "INVALID_SCOPE"
    NO_EVIDENCE_FOUND = "NO_EVIDENCE_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"
