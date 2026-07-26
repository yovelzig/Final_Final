"""ORM model for the `research_runs` table (Phase G1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class ResearchRunORM(Base):
    """One execution attempt at a `ResearchRequest`. Maps to the domain
    `ResearchRun`.

    `attempt_number` is unique per `request_id` (never reused - a retry
    after FAILED always inserts a new row with the next integer). At most
    one non-terminal run may exist per request at a time, enforced by the
    partial unique index below.
    """

    __tablename__ = "research_runs"
    __table_args__ = (
        UniqueConstraint(
            "request_id", "attempt_number",
            name="uq_research_runs_request_attempt_number",
        ),
        Index("ix_research_runs_request_id", "request_id"),
        Index("ix_research_runs_status", "status"),
        Index(
            "uq_research_runs_one_active_per_request",
            "request_id",
            unique=True,
            postgresql_where="status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED')",
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("research_requests.request_id", ondelete="RESTRICT"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False)

    failure_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    retryable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    provider_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
