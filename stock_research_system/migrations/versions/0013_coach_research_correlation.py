"""Phase G2D2: Coach-to-Live-Research correlation on learning_orchestrator_runs.

Adds the columns and indexes `WAITING_FOR_RESEARCH` (spec section 11) and
`COACH_RESEARCH_RESUME` (spec section 16) need to durably correlate a
paused Coach run with the automatic Live Research job it triggered:

- `trusted_account_id` (spec section 9): the caller's own
  `AuthenticatedPrincipal.account_id` at run creation. Added **nullable**
  because this table may already hold production rows: existing rows are
  backfilled only through the authoritative `user_accounts.learner_id`
  (unique) relationship - never by copying `learner_id` into
  `trusted_account_id`, and never by inventing a value. `NOT NULL` is
  applied only if that backfill resolves every row; if any row's learner
  has no linked account, the column is left nullable for legacy rows and
  the guarantee instead becomes an application-boundary requirement
  (`LearningOrchestratorService` already requires `trusted_account_id` to
  create a new run - see `service.py::start_run`/`stream_start_run`).
- `research_job_id` / `research_request_id` / `research_run_id` /
  `research_deadline_at` / `research_failure_category` /
  `evidence_count` (spec sections 11-12): nullable, populated only while
  (and after) a run is `WAITING_FOR_RESEARCH`.
- A partial unique index on `research_job_id` (non-null only), so a
  `LIVE_RESEARCH_RUN_EXECUTION` job can never be linked from more than
  one Coach run.
- A `(status, research_job_id)` index for the reconciliation sweep
  (spec section 13) to cheaply find `WAITING_FOR_RESEARCH` runs.

`WAITING_FOR_RESEARCH` itself is a `LearningOrchestratorRunStatus` value
stored in the existing `status` column (`String(24)`, unchanged) - no
migration is needed for the enum value itself, exactly as `0010_
langgraph_learning_orchestrator.py` already established for every other
status value.

Does not touch any official LangGraph checkpoint table, does not delete
any existing Coach row, and does not modify any other existing table,
extension, index, or hypertable.

Revision ID: 0013_coach_research_correlation
Revises: 0012_live_research_domain
Create Date: 2026-07-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0013_coach_research_correlation"
down_revision: Union[str, None] = "0012_live_research_domain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable initially: existing production Coach runs may already exist
    # and have no trusted_account_id yet. NOT NULL is applied conditionally
    # below, only if the backfill resolves every row.
    op.add_column(
        "learning_orchestrator_runs",
        sa.Column("trusted_account_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_learning_orchestrator_runs_trusted_account_id", "learning_orchestrator_runs",
        "user_accounts", ["trusted_account_id"], ["account_id"], ondelete="RESTRICT",
    )

    op.add_column(
        "learning_orchestrator_runs", sa.Column("research_job_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "learning_orchestrator_runs", sa.Column("research_request_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "learning_orchestrator_runs", sa.Column("research_run_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "learning_orchestrator_runs",
        sa.Column("research_deadline_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "learning_orchestrator_runs", sa.Column("research_failure_category", sa.String(100), nullable=True)
    )
    op.add_column("learning_orchestrator_runs", sa.Column("evidence_count", sa.Integer(), nullable=True))

    op.create_index(
        "uq_learning_orchestrator_runs_research_job_id", "learning_orchestrator_runs", ["research_job_id"],
        unique=True, postgresql_where=sa.text("research_job_id IS NOT NULL"),
    )
    op.create_index(
        "ix_learning_orchestrator_runs_status_research_job", "learning_orchestrator_runs",
        ["status", "research_job_id"],
    )

    # Authoritative backfill: join through user_accounts.learner_id, which
    # is unique, so this can never fan out to more than one candidate
    # account per run. Never copy learner_id into trusted_account_id, and
    # never invent an account id for a learner with no linked account.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE learning_orchestrator_runs AS runs
            SET trusted_account_id = accounts.account_id
            FROM user_accounts AS accounts
            WHERE accounts.learner_id = runs.learner_id
              AND runs.trusted_account_id IS NULL
            """
        )
    )

    unresolved_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM learning_orchestrator_runs WHERE trusted_account_id IS NULL"
        )
    ).scalar_one()

    if unresolved_count == 0:
        # Every existing row (including the empty-table case) resolved
        # safely, so it is now safe to enforce NOT NULL for all future rows.
        op.alter_column(
            "learning_orchestrator_runs", "trusted_account_id", existing_type=postgresql.UUID(as_uuid=True),
            nullable=False,
        )
    # else: some legacy rows have no authoritative account to backfill
    # from. Leave the column nullable for those rows - trusted_account_id
    # is still required for every *new* run at the application boundary
    # (LearningOrchestratorService.start_run / stream_start_run), which
    # never depends on this DB constraint.


def downgrade() -> None:
    op.drop_index("ix_learning_orchestrator_runs_status_research_job", table_name="learning_orchestrator_runs")
    op.drop_index("uq_learning_orchestrator_runs_research_job_id", table_name="learning_orchestrator_runs")
    op.drop_column("learning_orchestrator_runs", "evidence_count")
    op.drop_column("learning_orchestrator_runs", "research_failure_category")
    op.drop_column("learning_orchestrator_runs", "research_deadline_at")
    op.drop_column("learning_orchestrator_runs", "research_run_id")
    op.drop_column("learning_orchestrator_runs", "research_request_id")
    op.drop_column("learning_orchestrator_runs", "research_job_id")
    op.drop_constraint(
        "fk_learning_orchestrator_runs_trusted_account_id", "learning_orchestrator_runs", type_="foreignkey"
    )
    op.drop_column("learning_orchestrator_runs", "trusted_account_id")
