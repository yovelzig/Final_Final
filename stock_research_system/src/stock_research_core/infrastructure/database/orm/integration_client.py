"""ORM models for `integration_clients` and
`integration_client_allowed_job_types` (Phase 11 n8n integration)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, PrimaryKeyConstraint, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class IntegrationClientORM(Base):
    """An n8n (or other automation) API-key client. Maps to the domain `IntegrationClient`."""

    __tablename__ = "integration_clients"

    integration_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    key_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    api_key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntegrationClientAllowedJobTypeORM(Base):
    """Normalized association: which `BackgroundJobType`s an integration client may trigger."""

    __tablename__ = "integration_client_allowed_job_types"
    __table_args__ = (
        PrimaryKeyConstraint("integration_id", "job_type", name="pk_integration_client_allowed_job_types"),
    )

    integration_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("integration_clients.integration_id", ondelete="CASCADE"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
