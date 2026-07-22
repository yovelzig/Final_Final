"""Phase 11: background jobs, durable job attempts/events, and n8n
integration-client authentication.

PostgreSQL is the source of truth for job state - `background_jobs`
carries the full job lifecycle; `background_job_attempts` and
`background_job_events` are append-only audit trails. `integration_clients`
and `integration_client_allowed_job_types` hold n8n (or other automation)
API-key clients and the job types each may trigger; `integration_requests`
provides replay protection for inbound job-trigger requests.

No existing table, extension, index, or hypertable is modified.

Revision ID: 0009_operations_and_n8n
Revises: 0008_kb_doc_context_uniqueness
Create Date: 2026-07-20

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0009_operations_and_n8n"
down_revision: Union[str, None] = "0008_kb_doc_context_uniqueness"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- background_jobs -----------------------------------------------
    op.create_table(
        "background_jobs",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("trigger_source", sa.String(16), nullable=False),
        sa.Column("requested_by_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requested_by_integration_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requester_key", sa.String(120), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("resource_key", sa.String(300), nullable=True),
        sa.Column("parameters", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("result_summary", postgresql.JSONB(), nullable=True),
        sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("progress_message", sa.String(500), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("maximum_attempts", sa.Integer(), nullable=False),
        sa.Column("queue_name", sa.String(100), nullable=False),
        sa.Column("task_name", sa.String(200), nullable=False),
        sa.Column("task_id", sa.String(200), nullable=True),
        sa.Column("available_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("job_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["requested_by_account_id"], ["user_accounts.account_id"],
            name="fk_background_jobs_requested_by_account_id", ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "job_type", "trigger_source", "requester_key", "idempotency_key",
            name="uq_background_jobs_idempotency_scope",
        ),
        sa.CheckConstraint("progress_current >= 0", name="ck_background_jobs_progress_current_non_negative"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_background_jobs_attempt_count_non_negative"),
        sa.CheckConstraint(
            "maximum_attempts >= 1 AND maximum_attempts <= 20", name="ck_background_jobs_maximum_attempts_range"
        ),
    )
    op.create_index("ix_background_jobs_status", "background_jobs", ["status"])
    op.create_index("ix_background_jobs_job_type", "background_jobs", ["job_type"])
    op.create_index("ix_background_jobs_created_at", "background_jobs", ["created_at"])
    op.create_index("ix_background_jobs_resource_key", "background_jobs", ["resource_key"])
    op.create_index("ix_background_jobs_status_available_at", "background_jobs", ["status", "available_at"])

    # -- background_job_attempts -----------------------------------------------
    op.create_table(
        "background_job_attempts",
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("worker_name", sa.String(200), nullable=True),
        sa.Column("celery_task_id", sa.String(200), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_type", sa.String(200), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column("retry_delay_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["job_id"], ["background_jobs.job_id"], name="fk_background_job_attempts_job_id", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("job_id", "attempt_number", name="uq_background_job_attempts_job_attempt_number"),
        sa.CheckConstraint("attempt_number > 0", name="ck_background_job_attempts_attempt_number_positive"),
        sa.CheckConstraint(
            "retry_delay_seconds IS NULL OR retry_delay_seconds >= 0",
            name="ck_background_job_attempts_retry_delay_non_negative",
        ),
    )
    op.create_index("ix_background_job_attempts_job_id", "background_job_attempts", ["job_id"])

    # -- background_job_events -----------------------------------------------
    op.create_table(
        "background_job_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("message", sa.String(1000), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["job_id"], ["background_jobs.job_id"], name="fk_background_job_events_job_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["background_job_attempts.attempt_id"],
            name="fk_background_job_events_attempt_id", ondelete="SET NULL",
        ),
    )
    op.create_index("ix_background_job_events_event_type", "background_job_events", ["event_type"])
    op.create_index("ix_background_job_events_job_created", "background_job_events", ["job_id", "created_at"])
    op.create_index("ix_background_job_events_correlation_id", "background_job_events", ["correlation_id"])

    # -- integration_clients -----------------------------------------------
    op.create_table(
        "integration_clients",
        sa.Column("integration_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("key_id", sa.String(64), nullable=False),
        sa.Column("api_key_hash", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("key_id", name="uq_integration_clients_key_id"),
        sa.UniqueConstraint("api_key_hash", name="uq_integration_clients_api_key_hash"),
    )

    # -- integration_client_allowed_job_types -----------------------------------------------
    op.create_table(
        "integration_client_allowed_job_types",
        sa.Column("integration_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint(
            "integration_id", "job_type", name="pk_integration_client_allowed_job_types"
        ),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["integration_clients.integration_id"],
            name="fk_integration_client_allowed_job_types_integration_id", ondelete="CASCADE",
        ),
    )

    # -- integration_requests -----------------------------------------------
    op.create_table(
        "integration_requests",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("integration_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_request_id", sa.String(200), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["integration_clients.integration_id"],
            name="fk_integration_requests_integration_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["background_jobs.job_id"], name="fk_integration_requests_job_id", ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "integration_id", "external_request_id", name="uq_integration_requests_external_request_id"
        ),
        sa.UniqueConstraint("integration_id", "idempotency_key", name="uq_integration_requests_idempotency_key"),
    )
    op.create_index("ix_integration_requests_integration_id", "integration_requests", ["integration_id"])


def downgrade() -> None:
    op.drop_table("integration_requests")
    op.drop_table("integration_client_allowed_job_types")
    op.drop_table("integration_clients")
    op.drop_table("background_job_events")
    op.drop_table("background_job_attempts")
    op.drop_table("background_jobs")
