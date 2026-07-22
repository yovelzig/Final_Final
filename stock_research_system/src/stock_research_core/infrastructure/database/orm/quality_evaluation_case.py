"""ORM models for `quality_evaluation_cases` and its normalized reference
association tables (Phase 13)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class QualityEvaluationCaseORM(Base):
    __tablename__ = "quality_evaluation_cases"
    __table_args__ = (
        UniqueConstraint(
            "suite_id", "external_case_id", "case_version", name="uq_quality_evaluation_cases_suite_external_version"
        ),
        Index("ix_quality_evaluation_cases_suite_status", "suite_id", "status"),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    suite_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quality_evaluation_suites.suite_id", ondelete="CASCADE"), nullable=False
    )
    external_case_id: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    context_type: Mapped[str] = mapped_column(String(32), nullable=False)
    user_input: Mapped[str] = mapped_column(String(4000), nullable=False)

    reference_answer: Mapped[str | None] = mapped_column(String(8000), nullable=True)
    reference_contexts: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")

    expected_guardrail_category: Mapped[str | None] = mapped_column(String(48), nullable=True)
    expected_refusal: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    expected_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    expected_intent: Mapped[str | None] = mapped_column(String(48), nullable=True)
    expected_route: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expected_action_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    expected_interrupt: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    forbidden_phrases: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    required_concepts: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    case_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")

    case_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class QualityEvaluationCaseReferenceDocumentORM(Base):
    __tablename__ = "quality_evaluation_case_reference_documents"

    case_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quality_evaluation_cases.case_id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_documents.document_id", ondelete="CASCADE"), primary_key=True
    )


class QualityEvaluationCaseReferenceChunkORM(Base):
    __tablename__ = "quality_evaluation_case_reference_chunks"

    case_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quality_evaluation_cases.case_id", ondelete="CASCADE"), primary_key=True
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_chunks.chunk_id", ondelete="CASCADE"), primary_key=True
    )


class QualityEvaluationCaseSkillORM(Base):
    __tablename__ = "quality_evaluation_case_skills"

    case_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quality_evaluation_cases.case_id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("financial_skills.skill_id", ondelete="CASCADE"), primary_key=True
    )
