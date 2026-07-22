"""ORM model for the `user_progress` table.

A single row tracks progress toward exactly one target granularity
(path, module, or lesson). Because plain SQL `UNIQUE` constraints treat
`NULL` as distinct from `NULL` (so a normal unique constraint spanning
all three nullable FK columns would never actually prevent duplicates),
"no duplicate progress record for the same target" is enforced with
three partial unique indexes, one per granularity, each only covering
rows where that particular column is set.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class UserProgressORM(Base):
    """A learner's progress toward a path, module, or lesson."""

    __tablename__ = "user_progress"
    __table_args__ = (
        Index("ix_user_progress_learner_id", "learner_id"),
        Index("ix_user_progress_status", "status"),
        Index(
            "uq_user_progress_path",
            "learner_id",
            "path_id",
            unique=True,
            postgresql_where="path_id IS NOT NULL",
        ),
        Index(
            "uq_user_progress_module",
            "learner_id",
            "module_id",
            unique=True,
            postgresql_where="module_id IS NOT NULL",
        ),
        Index(
            "uq_user_progress_lesson",
            "learner_id",
            "lesson_id",
            unique=True,
            postgresql_where="lesson_id IS NOT NULL",
        ),
    )

    progress_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    learner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("learner_profiles.learner_id", ondelete="RESTRICT"),
        nullable=False,
    )
    path_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("learning_paths.path_id", ondelete="RESTRICT"), nullable=True
    )
    module_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("learning_modules.module_id", ondelete="RESTRICT"),
        nullable=True,
    )
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("lessons.lesson_id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    completion_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    best_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
