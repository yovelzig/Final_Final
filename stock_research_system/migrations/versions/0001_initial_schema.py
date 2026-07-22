"""Initial Phase 3 schema: securities, market_bars (hypertable), ingestion runs,
quality issues, and tracked securities.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-14

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")

    op.create_table(
        "securities",
        sa.Column("security_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("company_name", sa.String(250), nullable=False),
        sa.Column("exchange", sa.String(30), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("sector", sa.String(250), nullable=True),
        sa.Column("industry", sa.String(250), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("ticker", "exchange", name="uq_securities_ticker_exchange"),
    )
    op.create_index("ix_securities_ticker", "securities", ["ticker"])
    op.create_index("ix_securities_active", "securities", ["active"])

    op.create_table(
        "market_bars",
        sa.Column("security_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("interval", sa.String(20), nullable=False),
        sa.Column("source_name", sa.String(250), nullable=False),
        sa.Column("open", sa.Numeric(20, 8), nullable=False),
        sa.Column("high", sa.Numeric(20, 8), nullable=False),
        sa.Column("low", sa.Numeric(20, 8), nullable=False),
        sa.Column("close", sa.Numeric(20, 8), nullable=False),
        sa.Column("adjusted_close", sa.Numeric(20, 8), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["security_id"],
            ["securities.security_id"],
            name="fk_market_bars_security_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "security_id", "timestamp", "interval", "source_name", name="pk_market_bars"
        ),
    )
    op.create_index("ix_market_bars_security_timestamp", "market_bars", ["security_id", "timestamp"])
    op.create_index(
        "ix_market_bars_security_interval_timestamp",
        "market_bars",
        ["security_id", "interval", "timestamp"],
    )
    op.create_index("ix_market_bars_timestamp", "market_bars", ["timestamp"])

    # Convert to a TimescaleDB hypertable partitioned by `timestamp`. The
    # primary key above already includes `timestamp`, which TimescaleDB
    # requires of every unique/primary-key constraint on a hypertable.
    op.execute(
        "SELECT create_hypertable('market_bars', 'timestamp', if_not_exists => TRUE);"
    )

    op.create_table(
        "market_data_ingestion_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("security_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_name", sa.String(250), nullable=False),
        sa.Column("interval", sa.String(20), nullable=False),
        sa.Column("requested_start_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("requested_end_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("is_incremental", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("provider_rows_received", sa.Integer(), nullable=False),
        sa.Column("valid_bars_returned", sa.Integer(), nullable=False),
        sa.Column("bars_persisted", sa.Integer(), nullable=False),
        sa.Column("duplicate_rows_removed", sa.Integer(), nullable=False),
        sa.Column("invalid_rows_removed", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_type", sa.String(250), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["security_id"],
            ["securities.security_id"],
            name="fk_ingestion_runs_security_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_ingestion_runs_security_started",
        "market_data_ingestion_runs",
        ["security_id", "started_at"],
    )
    op.create_index("ix_ingestion_runs_status", "market_data_ingestion_runs", ["status"])
    op.create_index(
        "ix_ingestion_runs_provider_name", "market_data_ingestion_runs", ["provider_name"]
    )

    op.create_table(
        "market_data_quality_issues",
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["market_data_ingestion_runs.run_id"],
            name="fk_quality_issues_run_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_quality_issues_run_id", "market_data_quality_issues", ["run_id"])
    op.create_index("ix_quality_issues_code", "market_data_quality_issues", ["code"])
    op.create_index("ix_quality_issues_severity", "market_data_quality_issues", ["severity"])

    op.create_table(
        "tracked_securities",
        sa.Column("security_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("monitoring_started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_successful_update_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("next_scheduled_update_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("alert_threshold_probability_change", sa.Numeric(8, 6), nullable=False),
        sa.Column("alert_threshold_expected_return_change", sa.Numeric(8, 6), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["security_id"],
            ["securities.security_id"],
            name="fk_tracked_securities_security_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_tracked_securities_enabled", "tracked_securities", ["enabled"])
    op.create_index(
        "ix_tracked_securities_next_scheduled_update_at",
        "tracked_securities",
        ["next_scheduled_update_at"],
    )


def downgrade() -> None:
    op.drop_table("tracked_securities")
    op.drop_table("market_data_quality_issues")
    op.drop_table("market_data_ingestion_runs")
    op.drop_table("market_bars")
    op.drop_table("securities")
