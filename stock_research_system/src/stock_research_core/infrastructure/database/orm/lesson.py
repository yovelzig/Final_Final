"""ORM models for `lessons` and the `lesson_secondary_skills` association table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class LessonORM(Base):
    """A single short lesson within a `LearningModule`."""

    __tablename__ = "lessons"
    __table_args__ = (
        UniqueConstraint("module_id", "code", name="uq_lessons_module_code"),
        Index("ix_lessons_module_position", "module_id", "position"),
        Index("ix_lessons_primary_skill_id", "primary_skill_id"),
    )

    lesson_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    module_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("learning_modules.module_id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(String(2000), nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    primary_skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("financial_skills.skill_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class LessonSecondarySkillORM(Base):
    """Association table: which additional skills a lesson also practices."""

    __tablename__ = "lesson_secondary_skills"

    lesson_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("lessons.lesson_id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("financial_skills.skill_id", ondelete="RESTRICT"),
        primary_key=True,
    )
