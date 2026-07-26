"""ORM model for the `research_requests` table (Phase G1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class ResearchRequestORM(Base):
    """A single research question. Maps to the domain `ResearchRequest`."""

    __tablename__ = "research_requests"
    __table_args__ = (
        UniqueConstraint(
            "requester_key", "idempotency_key",
            name="uq_research_requests_idempotency_scope",
        ),
        Index("ix_research_requests_subject_security_id", "subject_security_id"),
        Index("ix_research_requests_created_at", "created_at"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)

    requested_by_account_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    requested_by_integration_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    #: `account:{id}` / `integration:{id}` - computed once at write time by
    #: the repository (same convention as `BackgroundJobORM.requester_key`)
    #: so the idempotency-scope unique constraint is a plain, non-nullable
    #: composite key.
    requester_key: Mapped[str] = mapped_column(String(120), nullable=False)

    original_question: Mapped[str] = mapped_column(String(5000), nullable=False)
    normalized_query: Mapped[str] = mapped_column(String(2000), nullable=False)

    subject_security_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("securities.security_id", ondelete="RESTRICT"), nullable=True
    )
    subject_raw_text: Mapped[str | None] = mapped_column(String(250), nullable=True)

    scope: Mapped[str] = mapped_column(String(32), nullable=False)

    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
