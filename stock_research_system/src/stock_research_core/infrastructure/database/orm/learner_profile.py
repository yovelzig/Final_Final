"""ORM model for the `learner_profiles` table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class LearnerProfileORM(Base):
    """A learner using the platform. Never stores credentials."""

    __tablename__ = "learner_profiles"

    learner_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    preferred_language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    financial_experience_level: Mapped[str] = mapped_column(String(20), nullable=False)
    daily_goal_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
