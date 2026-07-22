"""ORM model for the `background_jobs` table (Phase 11)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class BackgroundJobORM(Base):
    """A durable background job. Maps to the domain `BackgroundJob`."""

    __tablename__ = "background_jobs"
    __table_args__ = (
        UniqueConstraint(
            "job_type", "trigger_source", "requester_key", "idempotency_key",
            name="uq_background_jobs_idempotency_scope",
        ),
        Index("ix_background_jobs_status", "status"),
        Index("ix_background_jobs_job_type", "job_type"),
        Index("ix_background_jobs_created_at", "created_at"),
        Index("ix_background_jobs_resource_key", "resource_key"),
        Index("ix_background_jobs_status_available_at", "status", "available_at"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)

    trigger_source: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_by_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    requested_by_integration_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    #: `account:{id}` / `integration:{id}` / `source:{trigger_source}` -
    #: computed once at write time by the repository so the idempotency-scope
    #: unique constraint can be a plain (non-nullable) composite key instead
    #: of relying on multi-column NULL semantics.
    requester_key: Mapped[str] = mapped_column(String(120), nullable=False)

    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    resource_key: Mapped[str | None] = mapped_column(String(300), nullable=True)

    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    result_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    progress_current: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    progress_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    maximum_attempts: Mapped[int] = mapped_column(Integer, nullable=False)

    queue_name: Mapped[str] = mapped_column(String(100), nullable=False)
    task_name: Mapped[str] = mapped_column(String(200), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
