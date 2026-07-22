"""Phase 13: FinQuest-owned schema for the quality-evaluation platform
(versioned suites/cases, runs, sample results, deterministic + RAGAS
metric results, admin-approved baselines, and learning-outcome
aggregates).

RAGAS itself is never referenced here - this migration only creates the
canonical PostgreSQL persistence for evaluation lineage/results, which
remains authoritative regardless of which evaluator adapter produced a
RAGAS-mode metric.

No existing table, extension, index, or hypertable is modified.

Revision ID: 0011_ragas_learning_quality
Revises: 0010_langgraph_orchestrator
Create Date: 2026-07-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0011_ragas_learning_quality"
down_revision: Union[str, None] = "0010_langgraph_orchestrator"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- quality_evaluation_suites -----------------------------------------------
    op.create_table(
        "quality_evaluation_suites",
        sa.Column("suite_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False, server_default=""),
        sa.Column("suite_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dataset_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", "version", name="uq_quality_evaluation_suites_code_version"),
        sa.CheckConstraint("case_count >= 0", name="ck_quality_evaluation_suites_case_count_non_negative"),
    )
    op.create_index("ix_quality_evaluation_suites_status", "quality_evaluation_suites", ["status"])

    # -- quality_evaluation_cases -----------------------------------------------
    op.create_table(
        "quality_evaluation_cases",
        sa.Column("case_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("suite_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_case_id", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("context_type", sa.String(32), nullable=False),
        sa.Column("user_input", sa.String(4000), nullable=False),
        sa.Column("reference_answer", sa.String(8000), nullable=True),
        sa.Column("reference_contexts", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("expected_guardrail_category", sa.String(48), nullable=True),
        sa.Column("expected_refusal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("expected_fallback", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("expected_intent", sa.String(48), nullable=True),
        sa.Column("expected_route", sa.String(32), nullable=True),
        sa.Column("expected_action_type", sa.String(48), nullable=True),
        sa.Column("expected_interrupt", sa.Boolean(), nullable=True),
        sa.Column("forbidden_phrases", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("required_concepts", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("case_version", sa.String(50), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["suite_id"], ["quality_evaluation_suites.suite_id"],
            name="fk_quality_evaluation_cases_suite_id", ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "suite_id", "external_case_id", "case_version", name="uq_quality_evaluation_cases_suite_external_version"
        ),
    )
    op.create_index("ix_quality_evaluation_cases_suite_status", "quality_evaluation_cases", ["suite_id", "status"])

    # -- normalized case reference associations -----------------------------------------------
    op.create_table(
        "quality_evaluation_case_reference_documents",
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("case_id", "document_id", name="pk_quality_evaluation_case_reference_documents"),
        sa.ForeignKeyConstraint(
            ["case_id"], ["quality_evaluation_cases.case_id"],
            name="fk_quality_evaluation_case_ref_documents_case_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["knowledge_documents.document_id"],
            name="fk_quality_evaluation_case_ref_documents_document_id", ondelete="CASCADE",
        ),
    )
    op.create_table(
        "quality_evaluation_case_reference_chunks",
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("case_id", "chunk_id", name="pk_quality_evaluation_case_reference_chunks"),
        sa.ForeignKeyConstraint(
            ["case_id"], ["quality_evaluation_cases.case_id"],
            name="fk_quality_evaluation_case_ref_chunks_case_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["knowledge_chunks.chunk_id"],
            name="fk_quality_evaluation_case_ref_chunks_chunk_id", ondelete="CASCADE",
        ),
    )
    op.create_table(
        "quality_evaluation_case_skills",
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("case_id", "skill_id", name="pk_quality_evaluation_case_skills"),
        sa.ForeignKeyConstraint(
            ["case_id"], ["quality_evaluation_cases.case_id"],
            name="fk_quality_evaluation_case_skills_case_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["financial_skills.skill_id"],
            name="fk_quality_evaluation_case_skills_skill_id", ondelete="CASCADE",
        ),
    )

    # -- quality_evaluation_runs -----------------------------------------------
    op.create_table(
        "quality_evaluation_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("suite_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("requested_by_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("background_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("system_version", sa.String(100), nullable=False),
        sa.Column("git_commit", sa.String(64), nullable=True),
        sa.Column("retrieval_policy_version", sa.String(50), nullable=False),
        sa.Column("embedding_model", sa.String(100), nullable=False),
        sa.Column("embedding_version", sa.String(50), nullable=False),
        sa.Column("tutor_policy_version", sa.String(50), nullable=False),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("guardrail_version", sa.String(50), nullable=False),
        sa.Column("graph_version", sa.String(50), nullable=True),
        sa.Column("evaluator_provider", sa.String(100), nullable=True),
        sa.Column("evaluator_model", sa.String(100), nullable=True),
        sa.Column("ragas_version", sa.String(50), nullable=True),
        sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("dataset_hash", sa.String(64), nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["suite_id"], ["quality_evaluation_suites.suite_id"],
            name="fk_quality_evaluation_runs_suite_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_account_id"], ["user_accounts.account_id"],
            name="fk_quality_evaluation_runs_requested_by", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["background_job_id"], ["background_jobs.job_id"],
            name="fk_quality_evaluation_runs_background_job_id", ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "completed_case_count >= 0 AND failed_case_count >= 0 AND skipped_case_count >= 0 AND case_count >= 0",
            name="ck_quality_evaluation_runs_counts_non_negative",
        ),
    )
    op.create_index("ix_quality_evaluation_runs_suite_created", "quality_evaluation_runs", ["suite_id", "created_at"])
    op.create_index("ix_quality_evaluation_runs_status", "quality_evaluation_runs", ["status"])
    # Idempotent run creation is scoped per suite - a NULL idempotency_key
    # (older/manual runs) is never deduplicated (Postgres treats each NULL
    # as distinct in a unique index, which is the desired behavior here).
    op.create_index(
        "uq_quality_evaluation_runs_suite_idempotency", "quality_evaluation_runs",
        ["suite_id", "idempotency_key"], unique=True,
    )

    # -- quality_evaluation_sample_results -----------------------------------------------
    op.create_table(
        "quality_evaluation_sample_results",
        sa.Column("sample_result_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("generated_response", sa.String(8000), nullable=True),
        sa.Column("observed_guardrail_category", sa.String(48), nullable=True),
        sa.Column("observed_intent", sa.String(48), nullable=True),
        sa.Column("observed_route", sa.String(32), nullable=True),
        sa.Column("observed_action_type", sa.String(48), nullable=True),
        sa.Column("observed_interrupt", sa.Boolean(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retrieval_latency_ms", sa.Integer(), nullable=True),
        sa.Column("generation_latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_token_count", sa.Integer(), nullable=True),
        sa.Column("output_token_count", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(12, 6), nullable=True),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.Column("failure_message", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["run_id"], ["quality_evaluation_runs.run_id"],
            name="fk_quality_evaluation_sample_results_run_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["quality_evaluation_cases.case_id"],
            name="fk_quality_evaluation_sample_results_case_id", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("run_id", "case_id", name="uq_quality_evaluation_sample_results_run_case"),
        sa.CheckConstraint("latency_ms >= 0", name="ck_quality_evaluation_sample_results_latency_non_negative"),
        sa.CheckConstraint(
            "estimated_cost IS NULL OR estimated_cost >= 0", name="ck_quality_evaluation_sample_results_cost_non_negative"
        ),
    )
    op.create_index(
        "ix_quality_evaluation_sample_results_run_status", "quality_evaluation_sample_results", ["run_id", "status"]
    )

    op.create_table(
        "quality_evaluation_sample_retrieved_documents",
        sa.Column("sample_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "sample_result_id", "document_id", name="pk_quality_evaluation_sample_retrieved_documents"
        ),
        sa.ForeignKeyConstraint(
            ["sample_result_id"], ["quality_evaluation_sample_results.sample_result_id"],
            name="fk_quality_evaluation_sample_ret_documents_sample_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["knowledge_documents.document_id"],
            name="fk_quality_evaluation_sample_ret_documents_document_id", ondelete="CASCADE",
        ),
    )
    op.create_table(
        "quality_evaluation_sample_retrieved_chunks",
        sa.Column("sample_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("sample_result_id", "chunk_id", name="pk_quality_evaluation_sample_retrieved_chunks"),
        sa.ForeignKeyConstraint(
            ["sample_result_id"], ["quality_evaluation_sample_results.sample_result_id"],
            name="fk_quality_evaluation_sample_ret_chunks_sample_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["knowledge_chunks.chunk_id"],
            name="fk_quality_evaluation_sample_ret_chunks_chunk_id", ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "sample_result_id", "rank", name="uq_quality_evaluation_sample_retrieved_chunks_rank"
        ),
        sa.CheckConstraint("rank >= 0", name="ck_quality_evaluation_sample_retrieved_chunks_rank_non_negative"),
    )
    op.create_table(
        "quality_evaluation_sample_citations",
        sa.Column("sample_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("sample_result_id", "chunk_id", name="pk_quality_evaluation_sample_citations"),
        sa.ForeignKeyConstraint(
            ["sample_result_id"], ["quality_evaluation_sample_results.sample_result_id"],
            name="fk_quality_evaluation_sample_citations_sample_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["knowledge_chunks.chunk_id"],
            name="fk_quality_evaluation_sample_citations_chunk_id", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("sample_result_id", "ordinal", name="uq_quality_evaluation_sample_citations_ordinal"),
        sa.CheckConstraint("ordinal >= 0", name="ck_quality_evaluation_sample_citations_ordinal_non_negative"),
    )

    # -- quality_metric_results -----------------------------------------------
    op.create_table(
        "quality_metric_results",
        sa.Column("metric_result_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sample_result_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("metric_name", sa.String(100), nullable=False),
        sa.Column("metric_type", sa.String(24), nullable=False),
        sa.Column("metric_version", sa.String(50), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("evaluator_provider", sa.String(100), nullable=True),
        sa.Column("evaluator_model", sa.String(100), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["run_id"], ["quality_evaluation_runs.run_id"],
            name="fk_quality_metric_results_run_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sample_result_id"], ["quality_evaluation_sample_results.sample_result_id"],
            name="fk_quality_metric_results_sample_id", ondelete="CASCADE",
        ),
    )
    op.create_index("ix_quality_metric_results_run_metric", "quality_metric_results", ["run_id", "metric_name"])
    # Per-sample metric results: unique per (run, sample, metric, version).
    op.create_index(
        "uq_quality_metric_results_per_sample", "quality_metric_results",
        ["run_id", "sample_result_id", "metric_name", "metric_version"],
        unique=True, postgresql_where=sa.text("sample_result_id IS NOT NULL"),
    )
    # Run-level aggregate metric results (sample_result_id IS NULL): unique
    # per (run, metric, version) - a separate partial index because
    # Postgres unique constraints treat every NULL as distinct, which
    # would otherwise let duplicate aggregate rows through.
    op.create_index(
        "uq_quality_metric_results_run_aggregate", "quality_metric_results",
        ["run_id", "metric_name", "metric_version"],
        unique=True, postgresql_where=sa.text("sample_result_id IS NULL"),
    )

    # -- quality_evaluation_baselines -----------------------------------------------
    op.create_table(
        "quality_evaluation_baselines",
        sa.Column("baseline_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("suite_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approved_by_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("metric_summary", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("safety_gate_summary", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("approved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["suite_id"], ["quality_evaluation_suites.suite_id"],
            name="fk_quality_evaluation_baselines_suite_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["quality_evaluation_runs.run_id"],
            name="fk_quality_evaluation_baselines_run_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_account_id"], ["user_accounts.account_id"],
            name="fk_quality_evaluation_baselines_approved_by", ondelete="SET NULL",
        ),
    )
    op.create_index("ix_quality_evaluation_baselines_suite_approved", "quality_evaluation_baselines", ["suite_id", "approved"])

    # -- learning_quality_aggregates -----------------------------------------------
    op.create_table(
        "learning_quality_aggregates",
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("metric_type", sa.String(48), nullable=False),
        sa.Column("period_start", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("period_end", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("cohort_key", sa.String(200), nullable=False),
        sa.Column("cohort_size", sa.Integer(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("calculation_version", sa.String(50), nullable=False),
        sa.Column("filters", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("filter_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("cohort_size >= 0 AND sample_count >= 0", name="ck_learning_quality_aggregates_counts_non_negative"),
        sa.CheckConstraint("period_start < period_end", name="ck_learning_quality_aggregates_period_order"),
        sa.UniqueConstraint(
            "metric_type", "period_start", "period_end", "cohort_key", "calculation_version", "filter_hash",
            name="uq_learning_quality_aggregates_identity",
        ),
    )
    op.create_index(
        "ix_learning_quality_aggregates_metric_period", "learning_quality_aggregates", ["metric_type", "period_start"]
    )


def downgrade() -> None:
    op.drop_table("learning_quality_aggregates")
    op.drop_table("quality_evaluation_baselines")
    op.drop_table("quality_metric_results")
    op.drop_table("quality_evaluation_sample_citations")
    op.drop_table("quality_evaluation_sample_retrieved_chunks")
    op.drop_table("quality_evaluation_sample_retrieved_documents")
    op.drop_table("quality_evaluation_sample_results")
    op.drop_table("quality_evaluation_runs")
    op.drop_table("quality_evaluation_case_skills")
    op.drop_table("quality_evaluation_case_reference_chunks")
    op.drop_table("quality_evaluation_case_reference_documents")
    op.drop_table("quality_evaluation_cases")
    op.drop_table("quality_evaluation_suites")
