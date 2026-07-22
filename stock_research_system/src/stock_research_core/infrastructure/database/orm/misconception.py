"""ORM models for `misconceptions` and the `misconception_evidence_attempts` table.

Uniqueness on (learner, skill, code) is only enforced while a
misconception is `ACTIVE` (a partial unique index), so a previously
`RESOLVED` misconception of the same code can be re-detected later as
a fresh row without conflicting with its resolved predecessor.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class MisconceptionORM(Base):
    """A known, evidence-backed misconception a learner appears to hold."""

    __tablename__ = "misconceptions"
    __table_args__ = (
        Index("ix_misconceptions_learner_id", "learner_id"),
        Index("ix_misconceptions_skill_id", "skill_id"),
        Index("ix_misconceptions_status", "status"),
        Index(
            "uq_misconceptions_active_learner_skill_code",
            "learner_id",
            "skill_id",
            "code",
            unique=True,
            postgresql_where="status = 'ACTIVE'",
        ),
    )

    misconception_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
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
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detector_version: Mapped[str] = mapped_column(String(50), nullable=False)


class MisconceptionEvidenceAttemptORM(Base):
    """Association table: which attempts serve as evidence for a misconception."""

    __tablename__ = "misconception_evidence_attempts"

    misconception_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("misconceptions.misconception_id", ondelete="CASCADE"),
        primary_key=True,
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("exercise_attempts.attempt_id", ondelete="RESTRICT"),
        primary_key=True,
    )
