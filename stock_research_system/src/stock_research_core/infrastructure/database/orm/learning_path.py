"""ORM model for the `learning_paths` table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class LearningPathORM(Base):
    """The top level of the curriculum hierarchy."""

    __tablename__ = "learning_paths"
    __table_args__ = (Index("ix_learning_paths_position", "position"),)

    path_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(3000), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
