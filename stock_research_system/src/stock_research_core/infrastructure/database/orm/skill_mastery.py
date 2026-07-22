"""ORM model for the `skill_mastery` table."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class SkillMasteryORM(Base):
    """A learner's current mastery of one skill. Unique per (learner, skill)."""

    __tablename__ = "skill_mastery"
    __table_args__ = (
        UniqueConstraint("learner_id", "skill_id", name="uq_skill_mastery_learner_skill"),
        Index("ix_skill_mastery_learner_id", "learner_id"),
        Index("ix_skill_mastery_skill_id", "skill_id"),
    )

    mastery_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
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
    mastery_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    mastery_level: Mapped[str] = mapped_column(String(20), nullable=False)
    correct_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_practiced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    calculation_version: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
