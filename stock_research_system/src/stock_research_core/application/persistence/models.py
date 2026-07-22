"""Application-level persistence result models.

Plain Pydantic models describing what happened when an ingestion result
was persisted. No SQLAlchemy or other infrastructure dependency here.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from stock_research_core.application.market_data.models import MarketDataIngestionResult
from stock_research_core.domain.models import DomainModel


class IngestionRunStatus(StrEnum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    NO_NEW_DATA = "NO_NEW_DATA"


class PersistenceCounts(DomainModel):
    """How much of an ingestion result was actually written to the database."""

    securities_upserted: int = Field(ge=0)
    bars_attempted: int = Field(ge=0)
    bars_persisted: int = Field(ge=0)
    quality_issues_persisted: int = Field(ge=0)


class IngestionRunRecord(DomainModel):
    """A stored ingestion-run audit record, independent of any ORM row."""

    run_id: UUID
    security_id: UUID
    provider_name: str = Field(min_length=1)
    interval: str = Field(min_length=1)
    requested_start_at: datetime
    requested_end_at: datetime
    is_incremental: bool
    status: IngestionRunStatus
    provider_rows_received: int = Field(ge=0)
    valid_bars_returned: int = Field(ge=0)
    bars_persisted: int = Field(ge=0)
    duplicate_rows_removed: int = Field(ge=0)
    invalid_rows_removed: int = Field(ge=0)
    started_at: datetime
    completed_at: datetime | None = None
    error_type: str | None = None
    error_message: str | None = None


class PersistedMarketDataResult(DomainModel):
    """The outcome of persisting a `MarketDataIngestionResult` to the database.

    `ingestion_result` uses the canonical stored Security and canonical
    Security IDs in every returned bar.
    """

    ingestion_result: MarketDataIngestionResult
    run_id: UUID
    persistence_counts: PersistenceCounts
    latest_stored_bar_at: datetime | None = None
    status: IngestionRunStatus
