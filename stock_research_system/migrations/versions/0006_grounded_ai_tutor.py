"""Grounded financial-education AI tutor and RAG engine schema (Phase 8):
knowledge sources/documents/chunks/embeddings, tutor conversations,
messages, answers, citations, guardrail decisions, retrieval-run audit
records, and tracked knowledge gaps.

Enables the PostgreSQL `vector` extension (pgvector) idempotently.
`vector` 0.7.2 is already bundled in this project's
`timescale/timescaledb:2.17.2-pg16` image (confirmed via
`pg_available_extensions` before writing this migration) alongside
`timescaledb` 2.17.2 - no custom Docker image was required.

`knowledge_chunk_embeddings.embedding` is a fixed-width `vector(384)`
column (the configured `EMBEDDING_DIMENSION` default for
`sentence-transformers/all-MiniLM-L6-v2`), indexed with an HNSW
cosine-distance index (`vector_cosine_ops`) - pgvector 0.7.2 supports
HNSW, which the spec prefers over IVFFlat when available.
Lexical search uses a GIN expression index over a small SQL helper
function, `knowledge_chunk_tsvector(heading_path, content)`, which
wraps `to_tsvector('english', array_to_string(heading_path, ' ') || '
' || content)`. PostgreSQL's two-argument `to_tsvector(regconfig,
text)` is STABLE, not IMMUTABLE - neither a `GENERATED ALWAYS AS ...
STORED` column nor a plain expression index will accept it directly.
Wrapping it in a same-body `LANGUAGE sql IMMUTABLE` function (the
config is a fixed literal, so this is safe) is the standard PostgreSQL
pattern for indexing `to_tsvector` output; repository queries must call
the same function so the planner can use this index.

Multi-valued *entity references* (skills) get their own association
table, matching the existing convention (e.g.
`historical_market_scenario_primary_skills`); `matched_rule_codes` and
`heading_path` are plain descriptive string lists, so they use
`postgresql.ARRAY(sa.Text())`, matching the existing convention for
`learning_objectives`.

Revision ID: 0006_grounded_ai_tutor
Revises: 0005_virtual_portfolios
Create Date: 2026-07-19

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006_grounded_ai_tutor"
down_revision: Union[str, None] = "0005_virtual_portfolios"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIMENSION = 384


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.execute(
        "CREATE OR REPLACE FUNCTION knowledge_chunk_tsvector(heading_path text[], content text) "
        "RETURNS tsvector AS $$ "
        "SELECT to_tsvector('english', array_to_string($1, ' ') || ' ' || $2) "
        "$$ LANGUAGE sql IMMUTABLE;"
    )

    # -- knowledge_sources -----------------------------------------------
    op.create_table(
        "knowledge_sources",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("approval_status", sa.String(20), nullable=False),
        sa.Column("canonical_url", sa.String(2000), nullable=True),
        sa.Column("publisher", sa.String(300), nullable=True),
        sa.Column("license_note", sa.Text(), nullable=True),
        sa.Column("default_language", sa.String(10), nullable=False),
        sa.Column("trusted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_knowledge_sources_source_type", "knowledge_sources", ["source_type"])
    op.create_index("ix_knowledge_sources_approval_status", "knowledge_sources", ["approval_status"])
    op.create_index("ix_knowledge_sources_trusted", "knowledge_sources", ["trusted"])

    # -- knowledge_documents -----------------------------------------------
    op.create_table(
        "knowledge_documents",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("approval_status", sa.String(20), nullable=False),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("available_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("effective_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("lesson_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("portfolio_context_code", sa.String(100), nullable=True),
        sa.Column("document_version", sa.String(50), nullable=False),
        sa.Column("parser_version", sa.String(50), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["source_id"], ["knowledge_sources.source_id"], name="fk_knowledge_documents_source_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"], ["lessons.lesson_id"], name="fk_knowledge_documents_lesson_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"], ["exercises.exercise_id"], name="fk_knowledge_documents_exercise_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"], ["historical_market_scenarios.scenario_id"],
            name="fk_knowledge_documents_scenario_id", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "content_hash", "document_version", name="uq_knowledge_documents_hash_version"
        ),
    )
    op.create_index("ix_knowledge_documents_source_id", "knowledge_documents", ["source_id"])
    op.create_index(
        "ix_knowledge_documents_status_approval", "knowledge_documents", ["status", "approval_status"]
    )
    op.create_index("ix_knowledge_documents_available_at", "knowledge_documents", ["available_at"])
    op.create_index("ix_knowledge_documents_language", "knowledge_documents", ["language"])
    op.create_index("ix_knowledge_documents_lesson_id", "knowledge_documents", ["lesson_id"])
    op.create_index("ix_knowledge_documents_exercise_id", "knowledge_documents", ["exercise_id"])
    op.create_index("ix_knowledge_documents_scenario_id", "knowledge_documents", ["scenario_id"])

    # -- knowledge_document_skills (association) -----------------------------------------------
    op.create_table(
        "knowledge_document_skills",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(
            ["document_id"], ["knowledge_documents.document_id"],
            name="fk_knowledge_document_skills_document", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["financial_skills.skill_id"], name="fk_knowledge_document_skills_skill",
            ondelete="RESTRICT",
        ),
    )

    # -- knowledge_chunks -----------------------------------------------
    op.create_table(
        "knowledge_chunks",
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("heading_path", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("estimated_token_count", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("effective_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("chunking_version", sa.String(50), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["document_id"], ["knowledge_documents.document_id"], name="fk_knowledge_chunks_document_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "document_id", "chunk_index", "chunking_version", name="uq_knowledge_chunks_document_index_version"
        ),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
    op.create_index("ix_knowledge_chunks_available_at", "knowledge_chunks", ["available_at"])
    op.execute(
        "CREATE INDEX ix_knowledge_chunks_content_tsv ON knowledge_chunks "
        "USING gin (knowledge_chunk_tsvector(heading_path, content));"
    )

    # -- knowledge_chunk_embeddings -----------------------------------------------
    op.create_table(
        "knowledge_chunk_embeddings",
        sa.Column("embedding_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("embedding_version", sa.String(50), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSION), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["knowledge_chunks.chunk_id"], name="fk_knowledge_chunk_embeddings_chunk_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "chunk_id", "embedding_model", "embedding_version",
            name="uq_knowledge_chunk_embeddings_chunk_model_version",
        ),
    )
    op.create_index("ix_knowledge_chunk_embeddings_chunk_id", "knowledge_chunk_embeddings", ["chunk_id"])
    # Prefer HNSW (pgvector >= 0.5.0, confirmed available at 0.7.2 in this image) over IVFFlat.
    op.execute(
        "CREATE INDEX ix_knowledge_chunk_embeddings_hnsw_cosine "
        "ON knowledge_chunk_embeddings USING hnsw (embedding vector_cosine_ops);"
    )

    # -- knowledge_ingestion_runs -----------------------------------------------
    op.create_table(
        "knowledge_ingestion_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("documents_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunks_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embeddings_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunking_version", sa.String(50), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("embedding_version", sa.String(50), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_type", sa.String(200), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_id"], ["knowledge_sources.source_id"], name="fk_knowledge_ingestion_runs_source_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["knowledge_documents.document_id"],
            name="fk_knowledge_ingestion_runs_document_id", ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_knowledge_ingestion_runs_source_id", "knowledge_ingestion_runs", ["source_id"])
    op.create_index("ix_knowledge_ingestion_runs_started_at", "knowledge_ingestion_runs", ["started_at"])
    op.create_index("ix_knowledge_ingestion_runs_status", "knowledge_ingestion_runs", ["status"])

    # -- tutor_conversations -----------------------------------------------
    op.create_table(
        "tutor_conversations",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("context_type", sa.String(50), nullable=False),
        sa.Column("lesson_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("knowledge_cutoff_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["learner_id"], ["learner_profiles.learner_id"], name="fk_tutor_conversations_learner_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"], ["lessons.lesson_id"], name="fk_tutor_conversations_lesson_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"], ["exercises.exercise_id"], name="fk_tutor_conversations_exercise_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"], ["historical_market_scenarios.scenario_id"],
            name="fk_tutor_conversations_scenario_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["virtual_portfolios.portfolio_id"], name="fk_tutor_conversations_portfolio_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_tutor_conversations_learner_status", "tutor_conversations", ["learner_id", "status"]
    )
    op.create_index("ix_tutor_conversations_context_type", "tutor_conversations", ["context_type"])

    # -- tutor_messages -----------------------------------------------
    op.create_table(
        "tutor_messages",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # clock_timestamp(), not now(): now() is transaction start time, so two
        # messages added within the same transaction would otherwise tie.
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["tutor_conversations.conversation_id"], name="fk_tutor_messages_conversation_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_tutor_messages_conversation_created", "tutor_messages", ["conversation_id", "created_at"]
    )

    # -- tutor_retrieval_runs -----------------------------------------------
    op.create_table(
        "tutor_retrieval_runs",
        sa.Column("retrieval_run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("knowledge_cutoff_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("retrieval_policy_version", sa.String(50), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("embedding_version", sa.String(50), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["tutor_conversations.conversation_id"],
            name="fk_tutor_retrieval_runs_conversation_id", ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_tutor_retrieval_runs_conversation_created",
        "tutor_retrieval_runs",
        ["conversation_id", "created_at"],
    )

    # -- tutor_retrieval_run_chunks (association) -----------------------------------------------
    op.create_table(
        "tutor_retrieval_run_chunks",
        sa.Column("retrieval_run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("rank", sa.Integer(), primary_key=True),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["retrieval_run_id"], ["tutor_retrieval_runs.retrieval_run_id"],
            name="fk_tutor_retrieval_run_chunks_run", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["knowledge_chunks.chunk_id"], name="fk_tutor_retrieval_run_chunks_chunk",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_tutor_retrieval_run_chunks_chunk_id", "tutor_retrieval_run_chunks", ["chunk_id"])

    # -- tutor_guardrail_decisions -----------------------------------------------
    op.create_table(
        "tutor_guardrail_decisions",
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_category", sa.String(50), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("matched_rule_codes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("safe_response_override", sa.Text(), nullable=True),
        sa.Column("policy_version", sa.String(50), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["tutor_conversations.conversation_id"],
            name="fk_tutor_guardrail_decisions_conversation_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["tutor_messages.message_id"], name="fk_tutor_guardrail_decisions_message_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_tutor_guardrail_decisions_conversation_id", "tutor_guardrail_decisions", ["conversation_id"]
    )
    op.create_index("ix_tutor_guardrail_decisions_action", "tutor_guardrail_decisions", ["action"])

    # -- tutor_answers -----------------------------------------------
    op.create_table(
        "tutor_answers",
        sa.Column("answer_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provider_type", sa.String(30), nullable=False),
        sa.Column("answer_markdown", sa.Text(), nullable=False),
        sa.Column("request_category", sa.String(50), nullable=False),
        sa.Column("grounding_status", sa.String(30), nullable=False),
        sa.Column("retrieval_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("guardrail_decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tutor_policy_version", sa.String(50), nullable=False),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("model_response_id", sa.String(200), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("validated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["tutor_conversations.conversation_id"], name="fk_tutor_answers_conversation_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["request_message_id"], ["tutor_messages.message_id"], name="fk_tutor_answers_request_message_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_run_id"], ["tutor_retrieval_runs.retrieval_run_id"],
            name="fk_tutor_answers_retrieval_run_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["guardrail_decision_id"], ["tutor_guardrail_decisions.decision_id"],
            name="fk_tutor_answers_guardrail_decision_id", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("request_message_id", name="uq_tutor_answers_request_message_id"),
    )
    op.create_index(
        "ix_tutor_answers_conversation_created", "tutor_answers", ["conversation_id", "created_at"]
    )
    op.create_index("ix_tutor_answers_status", "tutor_answers", ["status"])

    # -- tutor_answer_citations -----------------------------------------------
    op.create_table(
        "tutor_answer_citations",
        sa.Column("citation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("answer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("citation_number", sa.Integer(), nullable=False),
        sa.Column("quoted_excerpt", sa.String(500), nullable=False),
        sa.Column("source_title", sa.String(300), nullable=False),
        sa.Column("document_title", sa.String(300), nullable=False),
        sa.Column("heading_path", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["answer_id"], ["tutor_answers.answer_id"], name="fk_tutor_answer_citations_answer_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["knowledge_chunks.chunk_id"], name="fk_tutor_answer_citations_chunk_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "answer_id", "citation_number", name="uq_tutor_answer_citations_answer_number"
        ),
        sa.UniqueConstraint("answer_id", "chunk_id", name="uq_tutor_answer_citations_answer_chunk"),
    )
    op.create_index("ix_tutor_answer_citations_answer_id", "tutor_answer_citations", ["answer_id"])

    # -- tutor_knowledge_gaps -----------------------------------------------
    op.create_table(
        "tutor_knowledge_gaps",
        sa.Column("gap_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("normalized_question", sa.String(2000), nullable=False),
        sa.Column("context_type", sa.String(50), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("resolution_document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["learner_id"], ["learner_profiles.learner_id"], name="fk_tutor_knowledge_gaps_learner_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["tutor_conversations.conversation_id"],
            name="fk_tutor_knowledge_gaps_conversation_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["tutor_messages.message_id"], name="fk_tutor_knowledge_gaps_message_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolution_document_id"], ["knowledge_documents.document_id"],
            name="fk_tutor_knowledge_gaps_resolution_document_id", ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "uq_tutor_knowledge_gaps_unresolved_question_context",
        "tutor_knowledge_gaps",
        ["normalized_question", "context_type"],
        unique=True,
        postgresql_where=sa.text("NOT resolved"),
    )
    op.create_index("ix_tutor_knowledge_gaps_learner_id", "tutor_knowledge_gaps", ["learner_id"])
    op.create_index("ix_tutor_knowledge_gaps_resolved", "tutor_knowledge_gaps", ["resolved"])

    # -- tutor_knowledge_gap_skills (association) -----------------------------------------------
    op.create_table(
        "tutor_knowledge_gap_skills",
        sa.Column("gap_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(
            ["gap_id"], ["tutor_knowledge_gaps.gap_id"], name="fk_tutor_knowledge_gap_skills_gap",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["financial_skills.skill_id"], name="fk_tutor_knowledge_gap_skills_skill",
            ondelete="RESTRICT",
        ),
    )


def downgrade() -> None:
    op.drop_table("tutor_knowledge_gap_skills")
    op.drop_table("tutor_knowledge_gaps")
    op.drop_table("tutor_answer_citations")
    op.drop_table("tutor_answers")
    op.drop_table("tutor_guardrail_decisions")
    op.drop_table("tutor_retrieval_run_chunks")
    op.drop_table("tutor_retrieval_runs")
    op.drop_table("tutor_messages")
    op.drop_table("tutor_conversations")
    op.drop_table("knowledge_ingestion_runs")
    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunk_embeddings_hnsw_cosine;")
    op.drop_table("knowledge_chunk_embeddings")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_document_skills")
    op.drop_table("knowledge_documents")
    op.drop_table("knowledge_sources")
    op.execute("DROP FUNCTION IF EXISTS knowledge_chunk_tsvector(text[], text);")
