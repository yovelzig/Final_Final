"""ORM model for the `learning_modules` table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class LearningModuleORM(Base):
    """A themed group of lessons within a `LearningPath`."""

    __tablename__ = "learning_modules"
    __table_args__ = (
        UniqueConstraint("path_id", "code", name="uq_learning_modules_path_code"),
        Index("ix_learning_modules_path_position", "path_id", "position"),
    )

    module_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    path_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("learning_paths.path_id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(3000), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
