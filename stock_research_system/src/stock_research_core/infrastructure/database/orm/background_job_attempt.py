"""ORM model for the `background_job_attempts` table (Phase 11)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class BackgroundJobAttemptORM(Base):
    """One worker's attempt at a `BackgroundJob`. Maps to the domain `BackgroundJobAttempt`."""

    __tablename__ = "background_job_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number", name="uq_background_job_attempts_job_attempt_number"),
        Index("ix_background_job_attempts_job_id", "job_id"),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("background_jobs.job_id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    worker_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    error_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    retry_delay_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
