"""ORM models for `diagnostic_assessment_items` and the `diagnostic_item_skills`
association table.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class DiagnosticAssessmentItemORM(Base):
    """One exercise selected as part of a `DiagnosticAssessment`."""

    __tablename__ = "diagnostic_assessment_items"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id", "position", name="uq_diagnostic_items_assessment_position"
        ),
        UniqueConstraint(
            "assessment_id", "exercise_id", name="uq_diagnostic_items_assessment_exercise"
        ),
        Index("ix_diagnostic_items_assessment_id", "assessment_id"),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("diagnostic_assessments.assessment_id", ondelete="CASCADE"),
        nullable=False,
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("exercises.exercise_id", ondelete="RESTRICT"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("exercise_attempts.attempt_id", ondelete="RESTRICT"),
        nullable=True,
    )
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    normalized_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)


class DiagnosticItemSkillORM(Base):
    """Association table: which skills a diagnostic item targets."""

    __tablename__ = "diagnostic_item_skills"

    item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("diagnostic_assessment_items.item_id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("financial_skills.skill_id", ondelete="RESTRICT"),
        primary_key=True,
    )
