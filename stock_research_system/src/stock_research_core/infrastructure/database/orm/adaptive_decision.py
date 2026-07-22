"""ORM models for `adaptive_decisions` and its two association tables
(`adaptive_decision_target_skills`, `adaptive_decision_reasons`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class AdaptiveDecisionORM(Base):
    """One auditable adaptive-engine recommendation."""

    __tablename__ = "adaptive_decisions"
    __table_args__ = (
        Index("ix_adaptive_decisions_recommendation_type", "recommendation_type"),
        Index("ix_adaptive_decisions_status", "status"),
        Index("ix_adaptive_decisions_learner_generated", "learner_id", "generated_at"),
        Index("ix_adaptive_decisions_session_generated", "session_id", "generated_at"),
    )

    decision_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    learner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("learner_profiles.learner_id", ondelete="RESTRICT"),
        nullable=False,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("learning_sessions.session_id", ondelete="RESTRICT"),
        nullable=True,
    )
    recommendation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    recommended_exercise_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("exercises.exercise_id", ondelete="RESTRICT"), nullable=True
    )
    recommended_lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("lessons.lesson_id", ondelete="RESTRICT"), nullable=True
    )
    priority_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    recommended_difficulty_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdaptiveDecisionTargetSkillORM(Base):
    """Association table: which skills a decision targets."""

    __tablename__ = "adaptive_decision_target_skills"

    decision_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("adaptive_decisions.decision_id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("financial_skills.skill_id", ondelete="RESTRICT"),
        primary_key=True,
    )


class AdaptiveDecisionReasonORM(Base):
    """Association table: the reason codes attached to a decision."""

    __tablename__ = "adaptive_decision_reasons"

    decision_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("adaptive_decisions.decision_id", ondelete="CASCADE"),
        primary_key=True,
    )
    reason_code: Mapped[str] = mapped_column(String(40), primary_key=True)
