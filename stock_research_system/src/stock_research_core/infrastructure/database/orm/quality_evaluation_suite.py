"""ORM model for the `quality_evaluation_suites` table (Phase 13)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class QualityEvaluationSuiteORM(Base):
    __tablename__ = "quality_evaluation_suites"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_quality_evaluation_suites_code_version"),
        Index("ix_quality_evaluation_suites_status", "status"),
    )

    suite_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False, server_default="")
    suite_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False, server_default="en")
    case_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    dataset_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
