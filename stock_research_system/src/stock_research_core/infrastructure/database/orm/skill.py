"""ORM models for `financial_skills` and the `skill_prerequisites` association table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class FinancialSkillORM(Base):
    """A discrete, testable financial-literacy skill."""

    __tablename__ = "financial_skills"
    __table_args__ = (
        Index("ix_financial_skills_category", "category"),
        Index("ix_financial_skills_active", "active"),
    )

    skill_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(3000), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SkillPrerequisiteORM(Base):
    """Association table: which skills must be learned before `skill_id`."""

    __tablename__ = "skill_prerequisites"

    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("financial_skills.skill_id", ondelete="CASCADE"),
        primary_key=True,
    )
    prerequisite_skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("financial_skills.skill_id", ondelete="CASCADE"),
        primary_key=True,
    )
