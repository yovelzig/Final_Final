"""Shared domain models for the AI stock research system.

These models are the single source of truth for the shape of data that
flows between components. Every future component (ingestion, extraction,
analysis, prediction, storage, APIs) must accept and return these objects
instead of passing unvalidated dictionaries.

This module has no knowledge of any infrastructure (databases, queues,
HTTP frameworks, vector stores, orchestration engines, etc.).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from stock_research_core.domain.enums import (
    AlertSeverity,
    AnalysisStatus,
    CriticalPointType,
    Direction,
    DocumentType,
    EventType,
    Exchange,
    PredictionLabel,
)


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class DomainModel(BaseModel):
    """Base class for all domain models.

    Strict configuration is applied everywhere so invalid or unexpected
    data is rejected rather than silently accepted.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        protected_namespaces=(),
    )


class Security(DomainModel):
    """A tradeable security tracked by the system."""

    security_id: UUID = Field(default_factory=uuid4)
    ticker: str = Field(min_length=1, max_length=20)
    company_name: str = Field(min_length=1, max_length=250)
    exchange: Exchange
    currency: str = Field(default="USD", min_length=3, max_length=3)
    sector: str | None = None
    industry: str | None = None
    active: bool = True

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str) -> str:
        return value.upper()

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, value: str) -> str:
        return value.upper()


class AnalysisRequest(DomainModel):
    """A user's request to analyze a security."""

    request_id: UUID = Field(default_factory=uuid4)
    ticker: str | None = Field(default=None, min_length=1, max_length=20)
    company_name: str | None = Field(default=None, min_length=1, max_length=250)
    user_question: str = Field(min_length=3, max_length=5000)
    requested_horizons_days: list[int] = Field(default_factory=lambda: [5, 20, 60])
    as_of: datetime = Field(default_factory=utc_now)
    force_full_refresh: bool = False

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @field_validator("requested_horizons_days")
    @classmethod
    def _normalize_horizons(cls, value: list[int]) -> list[int]:
        if any(horizon <= 0 for horizon in value):
            raise ValueError("all requested horizons must be positive")
        deduplicated = sorted(set(value))
        if not deduplicated:
            raise ValueError("at least one requested horizon must remain")
        return deduplicated

    @model_validator(mode="after")
    def _require_identity(self) -> AnalysisRequest:
        if not self.ticker and not self.company_name:
            raise ValueError("either ticker or company_name must be provided")
        return self


class SourceDocument(DomainModel):
    """A raw source document: article, filing, report, transcript, or release."""

    document_id: UUID = Field(default_factory=uuid4)
    security_id: UUID
    document_type: DocumentType
    title: str = Field(min_length=1, max_length=1000)
    source_name: str = Field(min_length=1, max_length=250)
    canonical_url: HttpUrl | None = None
    source_document_id: str | None = None
    published_at: datetime
    retrieved_at: datetime = Field(default_factory=utc_now)
    language: str = Field(default="en", min_length=2, max_length=12)
    raw_text: str = Field(min_length=1)
    content_hash: str = Field(min_length=16, max_length=128)
    source_quality: float = Field(ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractedEvent(DomainModel):
    """A structured financial event extracted from a source document."""

    event_id: UUID = Field(default_factory=uuid4)
    security_id: UUID
    document_id: UUID
    event_type: EventType
    event_subtype: str | None = Field(default=None, max_length=200)
    occurred_at: datetime | None = None
    published_at: datetime
    direction: Direction
    sentiment_score: float = Field(ge=-1, le=1)
    magnitude_score: float = Field(ge=0, le=1)
    novelty_score: float = Field(ge=0, le=1)
    confidence_score: float = Field(ge=0, le=1)
    source_quality: float = Field(ge=0, le=1)
    expected_horizon_days: int | None = Field(default=None, gt=0)
    affected_metrics: list[str] = Field(default_factory=list)
    mentioned_entities: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1, max_length=3000)
    evidence_text: list[str] = Field(default_factory=list)
    extraction_version: str = Field(min_length=1)


class MarketBar(DomainModel):
    """A single OHLCV market price bar."""

    security_id: UUID
    timestamp: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    adjusted_close: float = Field(gt=0)
    volume: int = Field(ge=0)
    interval: str = Field(default="1d", min_length=1)
    source_name: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_ohlc_consistency(self) -> MarketBar:
        if self.high < self.open or self.high < self.close or self.high < self.low:
            raise ValueError("high must be greater than or equal to open, close, and low")
        if self.low > self.open or self.low > self.close or self.low > self.high:
            raise ValueError("low must be less than or equal to open, close, and high")
        return self


class CriticalPoint(DomainModel):
    """An important technical point detected in a stock price series."""

    point_id: UUID = Field(default_factory=uuid4)
    security_id: UUID
    timestamp: datetime
    point_type: CriticalPointType
    price: float = Field(gt=0)
    prominence: float = Field(ge=0)
    lookback_window: int = Field(gt=0)
    volume_zscore: float | None = None
    volatility_regime: str | None = None
    detection_method: str = Field(min_length=1)
    detector_version: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventMarketOutcome(DomainModel):
    """What happened to a stock's price after a specific event."""

    outcome_id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    security_id: UUID
    horizon_days: int = Field(gt=0)
    stock_return: float
    benchmark_return: float
    sector_return: float | None = None
    abnormal_return: float
    maximum_upside: float | None = None
    maximum_drawdown: float | None = None
    volume_change: float | None = None
    volatility_change: float | None = None
    measured_at: datetime
    calculation_version: str = Field(min_length=1)


class HorizonPrediction(DomainModel):
    """An ML prediction for a single investment horizon.

    This model never generates probabilities itself; it only validates
    values supplied by a future prediction engine.
    """

    prediction_id: UUID = Field(default_factory=uuid4)
    security_id: UUID
    as_of: datetime
    horizon_days: int = Field(gt=0)
    label: PredictionLabel
    probability_outperform: float | None = Field(default=None, ge=0, le=1)
    probability_neutral: float | None = Field(default=None, ge=0, le=1)
    probability_underperform: float | None = Field(default=None, ge=0, le=1)
    expected_excess_return: float | None = None
    expected_max_drawdown: float | None = None
    confidence_score: float = Field(ge=0, le=1)
    sample_size: int = Field(ge=0)
    model_name: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    feature_set_version: str = Field(min_length=1)
    data_cutoff_at: datetime
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_probabilities(self) -> HorizonPrediction:
        if self.label == PredictionLabel.INSUFFICIENT_EVIDENCE:
            return self

        probabilities = (
            self.probability_outperform,
            self.probability_neutral,
            self.probability_underperform,
        )
        if any(probability is None for probability in probabilities):
            raise ValueError(
                "probability_outperform, probability_neutral, and "
                "probability_underperform are required unless label is "
                "INSUFFICIENT_EVIDENCE"
            )

        total = sum(probabilities)  # type: ignore[arg-type]
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                "probability_outperform, probability_neutral, and "
                "probability_underperform must sum to 1.0 (tolerance 0.001)"
            )
        return self


class RiskAssessment(DomainModel):
    """A summary of risk factors for a security."""

    volatility_regime: str
    downside_risk_score: float = Field(ge=0, le=1)
    liquidity_risk_score: float = Field(ge=0, le=1)
    event_risk_score: float = Field(ge=0, le=1)
    overall_risk_score: float = Field(ge=0, le=1)
    risk_factors: list[str] = Field(default_factory=list)


class EvidenceItem(DomainModel):
    """A single source supporting a claim made in an analysis report."""

    document_id: UUID
    event_id: UUID | None = None
    title: str
    source_name: str
    published_at: datetime
    claim: str
    relevance_score: float = Field(ge=0, le=1)
    source_quality: float = Field(ge=0, le=1)


class DataFreshness(DomainModel):
    """Describes how up to date the data behind an analysis is."""

    latest_document_at: datetime | None = None
    latest_market_bar_at: datetime | None = None
    latest_prediction_at: datetime | None = None
    is_fresh: bool
    reasons: list[str] = Field(default_factory=list)


class AnalysisResponse(DomainModel):
    """The final structured response returned by the analysis system."""

    request_id: UUID
    analysis_id: UUID = Field(default_factory=uuid4)
    security: Security
    status: AnalysisStatus
    generated_at: datetime = Field(default_factory=utc_now)
    freshness: DataFreshness
    predictions: list[HorizonPrediction] = Field(default_factory=list)
    preferred_horizon_days: int | None = None
    risk_assessment: RiskAssessment | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    positive_catalysts: list[str] = Field(default_factory=list)
    negative_catalysts: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class TrackedSecurity(DomainModel):
    """A security being monitored on an ongoing basis."""

    security_id: UUID
    enabled: bool = True
    monitoring_started_at: datetime = Field(default_factory=utc_now)
    last_successful_update_at: datetime | None = None
    next_scheduled_update_at: datetime | None = None
    alert_threshold_probability_change: float = Field(default=0.10, ge=0, le=1)
    alert_threshold_expected_return_change: float = Field(default=0.03, ge=0)


class AlertCandidate(DomainModel):
    """A possible monitoring alert produced by comparing predictions over time."""

    alert_id: UUID = Field(default_factory=uuid4)
    security_id: UUID
    created_at: datetime = Field(default_factory=utc_now)
    severity: AlertSeverity
    title: str = Field(min_length=1, max_length=300)
    reason: str = Field(min_length=1, max_length=3000)
    previous_prediction_id: UUID | None = None
    current_prediction_id: UUID | None = None
    related_event_ids: list[UUID] = Field(default_factory=list)
    should_notify: bool
    suppression_reason: str | None = None
