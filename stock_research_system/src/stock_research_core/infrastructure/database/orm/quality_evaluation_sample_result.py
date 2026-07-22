"""ORM models for `quality_evaluation_sample_results` and its normalized
retrieved-evidence/citation association tables (Phase 13)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class QualityEvaluationSampleResultORM(Base):
    __tablename__ = "quality_evaluation_sample_results"
    __table_args__ = (
        UniqueConstraint("run_id", "case_id", name="uq_quality_evaluation_sample_results_run_case"),
        CheckConstraint("latency_ms >= 0", name="ck_quality_evaluation_sample_results_latency_non_negative"),
    )

    sample_result_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quality_evaluation_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quality_evaluation_cases.case_id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    generated_response: Mapped[str | None] = mapped_column(String(8000), nullable=True)

    observed_guardrail_category: Mapped[str | None] = mapped_column(String(48), nullable=True)
    observed_intent: Mapped[str | None] = mapped_column(String(48), nullable=True)
    observed_route: Mapped[str | None] = mapped_column(String(32), nullable=True)
    observed_action_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    observed_interrupt: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    retrieval_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    input_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)

    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class QualityEvaluationSampleRetrievedDocumentORM(Base):
    __tablename__ = "quality_evaluation_sample_retrieved_documents"

    sample_result_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("quality_evaluation_sample_results.sample_result_id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_documents.document_id", ondelete="CASCADE"), primary_key=True
    )


class QualityEvaluationSampleRetrievedChunkORM(Base):
    __tablename__ = "quality_evaluation_sample_retrieved_chunks"
    __table_args__ = (
        UniqueConstraint("sample_result_id", "rank", name="uq_quality_evaluation_sample_retrieved_chunks_rank"),
    )

    sample_result_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("quality_evaluation_sample_results.sample_result_id", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_chunks.chunk_id", ondelete="CASCADE"), primary_key=True
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)


class QualityEvaluationSampleCitationORM(Base):
    __tablename__ = "quality_evaluation_sample_citations"
    __table_args__ = (
        UniqueConstraint("sample_result_id", "ordinal", name="uq_quality_evaluation_sample_citations_ordinal"),
    )

    sample_result_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("quality_evaluation_sample_results.sample_result_id", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_chunks.chunk_id", ondelete="CASCADE"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
