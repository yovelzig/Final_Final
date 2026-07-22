"""ORM model for the `quality_evaluation_runs` table (Phase 13)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class QualityEvaluationRunORM(Base):
    __tablename__ = "quality_evaluation_runs"
    __table_args__ = (
        Index("ix_quality_evaluation_runs_suite_created", "suite_id", "created_at"),
        Index("ix_quality_evaluation_runs_status", "status"),
        CheckConstraint(
            "completed_case_count >= 0 AND failed_case_count >= 0 AND skipped_case_count >= 0 AND case_count >= 0",
            name="ck_quality_evaluation_runs_counts_non_negative",
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    suite_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quality_evaluation_suites.suite_id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)

    requested_by_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.account_id", ondelete="SET NULL"), nullable=True
    )
    background_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("background_jobs.job_id", ondelete="SET NULL"), nullable=True
    )

    system_version: Mapped[str] = mapped_column(String(100), nullable=False)
    git_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)

    retrieval_policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(50), nullable=False)
    tutor_policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    guardrail_version: Mapped[str] = mapped_column(String(50), nullable=False)
    graph_version: Mapped[str | None] = mapped_column(String(50), nullable=True)

    evaluator_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    evaluator_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ragas_version: Mapped[str | None] = mapped_column(String(50), nullable=True)

    case_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    completed_case_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_case_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    skipped_case_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    dataset_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
