"""ORM model for the `account_refresh_tokens` table. Only the token hash is stored - never the raw token."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class AccountRefreshTokenORM(Base):
    """Metadata for one issued refresh token."""

    __tablename__ = "account_refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_account_refresh_tokens_token_hash"),
        CheckConstraint("expires_at > issued_at", name="ck_account_refresh_tokens_expiration_after_issuance"),
        Index("ix_account_refresh_tokens_account_status", "account_id", "status"),
        Index("ix_account_refresh_tokens_token_family_id", "token_family_id"),
        Index("ix_account_refresh_tokens_expires_at", "expires_at"),
    )

    refresh_token_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.account_id", ondelete="CASCADE"), nullable=False
    )

    token_family_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_token_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("account_refresh_tokens.refresh_token_id", ondelete="SET NULL"),
        nullable=True,
    )

    user_agent_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    client_ip_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
