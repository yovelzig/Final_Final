"""ORM model for the `background_job_events` table (Phase 11)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class BackgroundJobEventORM(Base):
    """An immutable audit event for a `BackgroundJob`. Maps to the domain `BackgroundJobEvent`."""

    __tablename__ = "background_job_events"
    __table_args__ = (
        Index("ix_background_job_events_event_type", "event_type"),
        Index("ix_background_job_events_job_created", "job_id", "created_at"),
        Index("ix_background_job_events_correlation_id", "correlation_id"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("background_jobs.job_id", ondelete="CASCADE"), nullable=False
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("background_job_attempts.attempt_id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)

    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    event_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")

    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
