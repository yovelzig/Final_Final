"""ORM models for `knowledge_documents` and its skill-association table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class KnowledgeDocumentORM(Base):
    """One approved, retrievable unit of FinQuest educational content."""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        # Context-scoped (not just content+version): two different lessons
        # (or exercises/scenarios/sources) may legitimately share
        # byte-identical text - e.g. a short placeholder body reused across
        # curriculum items in tests/seed data - and must both remain
        # retrievable as distinct documents. `postgresql_nulls_not_distinct`
        # (PostgreSQL 15+) makes NULL-vs-NULL count as a match in the
        # remaining context columns, so a *local* document (which has no
        # lesson/exercise/scenario) is still deduplicated correctly by
        # (content_hash, document_version, source_id) alone.
        UniqueConstraint(
            "content_hash", "document_version", "source_id", "lesson_id", "exercise_id", "scenario_id",
            "portfolio_context_code", name="uq_knowledge_documents_hash_version_context",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_knowledge_documents_source_id", "source_id"),
        Index("ix_knowledge_documents_status_approval", "status", "approval_status"),
        Index("ix_knowledge_documents_available_at", "available_at"),
        Index("ix_knowledge_documents_language", "language"),
        Index("ix_knowledge_documents_lesson_id", "lesson_id"),
        Index("ix_knowledge_documents_exercise_id", "exercise_id"),
        Index("ix_knowledge_documents_scenario_id", "scenario_id"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    source_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_sources.source_id", ondelete="RESTRICT"), nullable=False
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False)
    approval_status: Mapped[str] = mapped_column(String(20), nullable=False)

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("lessons.lesson_id", ondelete="RESTRICT"), nullable=True
    )
    exercise_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("exercises.exercise_id", ondelete="RESTRICT"), nullable=True
    )
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("historical_market_scenarios.scenario_id", ondelete="RESTRICT"),
        nullable=True,
    )
    portfolio_context_code: Mapped[str | None] = mapped_column(String(100), nullable=True)

    document_version: Mapped[str] = mapped_column(String(50), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(50), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class KnowledgeDocumentSkillORM(Base):
    """Association: which financial skills a `KnowledgeDocument` relates to."""

    __tablename__ = "knowledge_document_skills"

    document_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_documents.document_id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("financial_skills.skill_id", ondelete="RESTRICT"), primary_key=True
    )
