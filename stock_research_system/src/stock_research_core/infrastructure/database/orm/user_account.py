"""ORM model for the `user_accounts` table.

`password_hash` is mapped here (the table owns the column) but is
never read by the public mapper (`identity_mappers.user_account_orm_to_domain`)
- only by the dedicated credential accessor used inside authentication
repository code.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class UserAccountORM(Base):
    """A local authentication identity."""

    __tablename__ = "user_accounts"
    __table_args__ = (
        UniqueConstraint("normalized_email", name="uq_user_accounts_normalized_email"),
        UniqueConstraint("learner_id", name="uq_user_accounts_learner_id"),
        CheckConstraint("failed_login_count >= 0", name="ck_user_accounts_failed_login_count_non_negative"),
        Index("ix_user_accounts_role", "role"),
        Index("ix_user_accounts_status", "status"),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    normalized_email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)

    learner_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("learner_profiles.learner_id", ondelete="RESTRICT"), nullable=True
    )
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
