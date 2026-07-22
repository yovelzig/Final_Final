"""Phase 12: FinQuest-owned audit/state tables for the LangGraph
personalized learning orchestrator.

These four tables are the *public, auditable* FinQuest product state
(thread ownership, run lifecycle, learner-safe events, proposed
actions). They are entirely separate from LangGraph's own official
checkpoint tables (created by `AsyncPostgresSaver.setup()` via the
explicit `learning_orchestrator_admin --setup-checkpointer` CLI command,
never by this migration and never reimplemented here as custom ORM
models - see `infrastructure.learning_orchestrator.postgres_checkpointer`).

No existing table, extension, index, or hypertable is modified.

Revision ID: 0010_langgraph_orchestrator
Revises: 0009_operations_and_n8n
Create Date: 2026-07-20

Note: `alembic_version.version_num` is `VARCHAR(32)` (see every prior
migration's "kept <=32 chars" note) - `0010_langgraph_learning_orchestrator`
(37 chars) does not fit, so the revision identifier is shortened to
`0010_langgraph_orchestrator` (27 chars) while this file keeps its
spec-mandated filename.

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0010_langgraph_orchestrator"
down_revision: Union[str, None] = "0009_operations_and_n8n"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- learning_orchestrator_threads -----------------------------------------------
    op.create_table(
        "learning_orchestrator_threads",
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("current_context_type", sa.String(32), nullable=False),
        sa.Column("linked_tutor_conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("graph_name", sa.String(100), nullable=False),
        sa.Column("graph_version", sa.String(50), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["learner_id"], ["learner_profiles.learner_id"],
            name="fk_learning_orchestrator_threads_learner_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["linked_tutor_conversation_id"], ["tutor_conversations.conversation_id"],
            name="fk_learning_orchestrator_threads_conversation_id", ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_learning_orchestrator_threads_learner_updated", "learning_orchestrator_threads",
        ["learner_id", "updated_at"],
    )
    op.create_index("ix_learning_orchestrator_threads_status", "learning_orchestrator_threads", ["status"])

    # -- learning_orchestrator_runs -----------------------------------------------
    op.create_table(
        "learning_orchestrator_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("output_tutor_answer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("intent", sa.String(48), nullable=True),
        sa.Column("route", sa.String(32), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("step_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("maximum_steps", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("waiting_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.Column("failure_message", sa.String(1000), nullable=True),
        sa.Column("graph_version", sa.String(50), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["learning_orchestrator_threads.thread_id"],
            name="fk_learning_orchestrator_runs_thread_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"], ["learner_profiles.learner_id"],
            name="fk_learning_orchestrator_runs_learner_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["input_message_id"], ["tutor_messages.message_id"],
            name="fk_learning_orchestrator_runs_input_message_id", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["output_tutor_answer_id"], ["tutor_answers.answer_id"],
            name="fk_learning_orchestrator_runs_output_answer_id", ondelete="SET NULL",
        ),
        sa.UniqueConstraint("thread_id", "idempotency_key", name="uq_learning_orchestrator_runs_thread_idempotency"),
        sa.CheckConstraint("step_count >= 0", name="ck_learning_orchestrator_runs_step_count_non_negative"),
        sa.CheckConstraint(
            "maximum_steps >= 1 AND maximum_steps <= 100", name="ck_learning_orchestrator_runs_maximum_steps_range"
        ),
    )
    op.create_index(
        "ix_learning_orchestrator_runs_thread_created", "learning_orchestrator_runs", ["thread_id", "created_at"]
    )
    op.create_index("ix_learning_orchestrator_runs_status", "learning_orchestrator_runs", ["status"])

    # -- learning_orchestrator_events -----------------------------------------------
    op.create_table(
        "learning_orchestrator_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("learner_message", sa.String(1000), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["run_id"], ["learning_orchestrator_runs.run_id"],
            name="fk_learning_orchestrator_events_run_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["learning_orchestrator_threads.thread_id"],
            name="fk_learning_orchestrator_events_thread_id", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("run_id", "sequence_number", name="uq_learning_orchestrator_events_run_sequence"),
        sa.CheckConstraint("sequence_number > 0", name="ck_learning_orchestrator_events_sequence_positive"),
    )
    op.create_index(
        "ix_learning_orchestrator_events_run_sequence", "learning_orchestrator_events", ["run_id", "sequence_number"]
    )

    # -- learning_orchestrator_action_proposals -----------------------------------------------
    op.create_table(
        "learning_orchestrator_action_proposals",
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_type", sa.String(48), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("result_reference", postgresql.JSONB(), nullable=True),
        sa.Column("approval_decision", sa.String(16), nullable=True),
        sa.Column("approval_payload", postgresql.JSONB(), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("proposed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("approved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("executed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"], ["learning_orchestrator_runs.run_id"],
            name="fk_learning_orchestrator_actions_run_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["learning_orchestrator_threads.thread_id"],
            name="fk_learning_orchestrator_actions_thread_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"], ["learner_profiles.learner_id"],
            name="fk_learning_orchestrator_actions_learner_id", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("run_id", "idempotency_key", name="uq_learning_orchestrator_actions_run_idempotency"),
    )
    op.create_index(
        "ix_learning_orchestrator_actions_status", "learning_orchestrator_action_proposals", ["status"]
    )


def downgrade() -> None:
    op.drop_table("learning_orchestrator_action_proposals")
    op.drop_table("learning_orchestrator_events")
    op.drop_table("learning_orchestrator_runs")
    op.drop_table("learning_orchestrator_threads")
