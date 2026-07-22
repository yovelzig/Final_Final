"""ORM model for the `integration_requests` table (Phase 11 n8n replay protection)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class IntegrationRequestORM(Base):
    """Replay-protection record for one inbound n8n job-trigger request.
    Maps to the domain `IntegrationRequest`."""

    __tablename__ = "integration_requests"
    __table_args__ = (
        UniqueConstraint(
            "integration_id", "external_request_id", name="uq_integration_requests_external_request_id"
        ),
        UniqueConstraint("integration_id", "idempotency_key", name="uq_integration_requests_idempotency_key"),
        Index("ix_integration_requests_integration_id", "integration_id"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    integration_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("integration_clients.integration_id", ondelete="CASCADE"), nullable=False
    )
    external_request_id: Mapped[str] = mapped_column(String(200), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)

    job_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("background_jobs.job_id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)

    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
