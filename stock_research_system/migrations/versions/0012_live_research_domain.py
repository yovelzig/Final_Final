"""Phase G1: provider-neutral Live Research domain.

Creates the durable schema for a research question (`research_requests`),
its execution attempts (`research_runs`), the provenance it gathers
(`evidence_items`), and the claims derived from that evidence
(`research_claims`, `claim_evidence_links`).

This migration is strictly provider-neutral: no Perplexity, SEC EDGAR,
yfinance, OpenAI, Ollama, n8n, or LangGraph concept is referenced. It
also does not touch the existing background-job/n8n-integration schema
from Phase 11 - a later phase wires a new `BackgroundJobType` handler on
top of this domain, not this migration.

No existing table, extension, index, or hypertable is modified.

Revision ID: 0012_live_research_domain
Revises: 0011_ragas_learning_quality
Create Date: 2026-07-26
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0012_live_research_domain"
down_revision: Union[str, None] = "0011_ragas_learning_quality"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- research_requests -----------------------------------------------
    op.create_table(
        "research_requests",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("requested_by_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requested_by_integration_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requester_key", sa.String(120), nullable=False),
        sa.Column("original_question", sa.String(5000), nullable=False),
        sa.Column("normalized_query", sa.String(2000), nullable=False),
        sa.Column("subject_security_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_raw_text", sa.String(250), nullable=True),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["subject_security_id"], ["securities.security_id"],
            name="fk_research_requests_subject_security_id", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "requester_key", "idempotency_key", name="uq_research_requests_idempotency_scope"
        ),
    )
    op.create_index("ix_research_requests_subject_security_id", "research_requests", ["subject_security_id"])
    op.create_index("ix_research_requests_created_at", "research_requests", ["created_at"])

    # -- research_runs -----------------------------------------------
    op.create_table(
        "research_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("failure_category", sa.String(32), nullable=True),
        sa.Column("failure_message", sa.String(2000), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=True),
        sa.Column("provider_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("queued_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["request_id"], ["research_requests.request_id"],
            name="fk_research_runs_request_id", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "request_id", "attempt_number", name="uq_research_runs_request_attempt_number"
        ),
        sa.CheckConstraint("attempt_number > 0", name="ck_research_runs_attempt_number_positive"),
    )
    op.create_index("ix_research_runs_request_id", "research_runs", ["request_id"])
    op.create_index("ix_research_runs_status", "research_runs", ["status"])
    # At most one non-terminal run may exist per request at a time - a
    # retry after FAILED always creates a new row (next attempt_number),
    # never reactivates the old one.
    op.create_index(
        "uq_research_runs_one_active_per_request",
        "research_runs",
        ["request_id"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED')"),
    )

    # -- evidence_items -----------------------------------------------
    op.create_table(
        "evidence_items",
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(48), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("source_url", sa.String(2000), nullable=True),
        sa.Column("official_identifier", sa.String(200), nullable=True),
        sa.Column("source_title", sa.String(1000), nullable=False),
        sa.Column("publisher", sa.String(250), nullable=False),
        sa.Column("retrieved_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("raw_excerpt", sa.String(5000), nullable=True),
        sa.Column("normalized_text", sa.String(5000), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("structured_facts", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"], ["research_runs.run_id"], name="fk_evidence_items_run_id", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("run_id", "content_hash", name="uq_evidence_items_run_content"),
    )
    op.create_index("ix_evidence_items_run_id", "evidence_items", ["run_id"])
    op.create_index("ix_evidence_items_source_type", "evidence_items", ["source_type"])

    # -- research_claims -----------------------------------------------
    op.create_table(
        "research_claims",
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_text", sa.String(2000), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("confidence_score", sa.Numeric(3, 2), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["run_id"], ["research_runs.run_id"], name="fk_research_claims_run_id", ondelete="CASCADE",
        ),
    )
    op.create_index("ix_research_claims_run_id", "research_claims", ["run_id"])
    op.create_index("ix_research_claims_status", "research_claims", ["status"])

    # -- claim_evidence_links -----------------------------------------------
    op.create_table(
        "claim_evidence_links",
        sa.Column("link_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stance", sa.String(24), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["claim_id"], ["research_claims.claim_id"],
            name="fk_claim_evidence_links_claim_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"], ["evidence_items.evidence_id"],
            name="fk_claim_evidence_links_evidence_id", ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "claim_id", "evidence_id", name="uq_claim_evidence_links_claim_evidence"
        ),
    )
    op.create_index("ix_claim_evidence_links_claim_id", "claim_evidence_links", ["claim_id"])
    op.create_index("ix_claim_evidence_links_evidence_id", "claim_evidence_links", ["evidence_id"])


def downgrade() -> None:
    op.drop_table("claim_evidence_links")
    op.drop_table("research_claims")
    op.drop_table("evidence_items")
    op.drop_table("research_runs")
    op.drop_table("research_requests")
