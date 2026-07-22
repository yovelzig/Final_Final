"""ORM model for the `exercise_adaptive_profiles` table.

`recommended_prerequisite_skill_ids` and `policy_tags` are stored as
native Postgres arrays rather than a separate association table: they
are soft, auxiliary metadata (not a core relationship the spec calls
out as requiring normalization, unlike target skills / reasons /
diagnostic skills / item skills elsewhere in this schema).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class ExerciseAdaptiveProfileORM(Base):
    """Adaptive metadata for an existing `Exercise`."""

    __tablename__ = "exercise_adaptive_profiles"
    __table_args__ = (
        Index("ix_exercise_adaptive_profiles_active", "active"),
        Index("ix_exercise_adaptive_profiles_diagnostic_eligible", "diagnostic_eligible"),
        Index("ix_exercise_adaptive_profiles_review_eligible", "review_eligible"),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("exercises.exercise_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    base_difficulty_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    estimated_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    diagnostic_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    remediation_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    minimum_mastery_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    maximum_mastery_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    recommended_prerequisite_skill_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list
    )
    policy_tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
