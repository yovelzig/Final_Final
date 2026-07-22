"""ORM models for `diagnostic_assessments` and the `diagnostic_assessment_skills`
association table.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class DiagnosticAssessmentORM(Base):
    """A diagnostic assessment covering one or more skills."""

    __tablename__ = "diagnostic_assessments"
    __table_args__ = (
        Index("ix_diagnostic_assessments_status", "status"),
        Index("ix_diagnostic_assessments_learner_created", "learner_id", "created_at"),
    )

    assessment_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    learner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("learner_profiles.learner_id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    maximum_items: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    policy_version: Mapped[str] = mapped_column(String(50), nullable=False)


class DiagnosticAssessmentSkillORM(Base):
    """Association table: which skills a diagnostic assessment covers."""

    __tablename__ = "diagnostic_assessment_skills"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("diagnostic_assessments.assessment_id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("financial_skills.skill_id", ondelete="RESTRICT"),
        primary_key=True,
    )
