"""ORM model for the append-only `authentication_audit_events` table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class AuthenticationAuditEventORM(Base):
    """One immutable authentication/security audit record. Rows are never updated after insert."""

    __tablename__ = "authentication_audit_events"
    __table_args__ = (
        Index("ix_authentication_audit_events_account_created", "account_id", "created_at"),
        Index("ix_authentication_audit_events_event_type", "event_type"),
        Index("ix_authentication_audit_events_result", "result"),
        Index("ix_authentication_audit_events_correlation_id", "correlation_id"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.account_id", ondelete="SET NULL"), nullable=True
    )

    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)

    correlation_id: Mapped[str] = mapped_column(String(200), nullable=False)
    email_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    client_ip_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_agent_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)

    reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
