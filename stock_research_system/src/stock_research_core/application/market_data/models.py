"""Application-level result models for market-data ingestion.

These describe the outcome of an ingestion operation (what was fetched
and how good the data is). They are plain Pydantic models, not database
or persistence models, and carry no infrastructure dependency.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from stock_research_core.domain.models import DomainModel, MarketBar, Security


class DataQualityIssue(DomainModel):
    """A single data-quality observation about an ingestion run."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: Literal["INFO", "WARNING", "ERROR"]
    timestamp: datetime | None = None


class MarketDataQualityReport(DomainModel):
    """Summarizes how much the provider's raw data had to be cleaned."""

    requested_start_at: datetime
    requested_end_at: datetime
    first_bar_at: datetime | None = None
    last_bar_at: datetime | None = None
    provider_rows_received: int = Field(ge=0)
    valid_bars_returned: int = Field(ge=0)
    duplicate_rows_removed: int = Field(ge=0)
    invalid_rows_removed: int = Field(ge=0)
    issues: list[DataQualityIssue] = Field(default_factory=list)


class MarketDataIngestionResult(DomainModel):
    """The outcome of fetching and normalizing market data for a security."""

    security: Security
    bars: list[MarketBar] = Field(default_factory=list)
    quality_report: MarketDataQualityReport
    is_incremental: bool
    provider_name: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_bars(self) -> MarketDataIngestionResult:
        timestamps = [bar.timestamp for bar in self.bars]
        if timestamps != sorted(timestamps):
            raise ValueError("bars must be sorted ascending by timestamp")
        if len(set(timestamps)) != len(timestamps):
            raise ValueError("bars must not contain duplicate timestamps")
        if any(bar.security_id != self.security.security_id for bar in self.bars):
            raise ValueError(
                "every MarketBar must share the security_id of the returned Security"
            )
        return self
