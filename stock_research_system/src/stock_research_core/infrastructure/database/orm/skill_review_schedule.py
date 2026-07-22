"""ORM model for the `skill_review_schedules` table."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class SkillReviewScheduleORM(Base):
    """A learner's spaced-repetition schedule for one skill. Unique per (learner, skill)."""

    __tablename__ = "skill_review_schedules"
    __table_args__ = (
        UniqueConstraint("learner_id", "skill_id", name="uq_review_schedules_learner_skill"),
        Index("ix_review_schedules_next_review_at", "next_review_at"),
        Index("ix_review_schedules_learner_status", "learner_id", "status"),
    )

    schedule_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    learner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("learner_profiles.learner_id", ondelete="RESTRICT"),
        nullable=False,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("financial_skills.skill_id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_interval_days: Mapped[int] = mapped_column(Integer, nullable=False)
    successful_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_successful_reviews: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ease_factor: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
