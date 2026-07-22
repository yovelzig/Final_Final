"""Virtual-portfolio and decision-journal engine schema: portfolios,
transactions, holdings, decision journal entries, valuation snapshots
(TimescaleDB hypertable), position valuations, risk assessments, and
valuation-run audit records.

`portfolio_valuation_snapshots` is a TimescaleDB hypertable partitioned
by `as_of`. TimescaleDB requires every unique/primary-key constraint on
a hypertable to include the partitioning column, so its primary key is
`(snapshot_id, as_of)` rather than `snapshot_id` alone. Because of
this, `portfolio_position_valuations.snapshot_id` and
`portfolio_risk_assessments.snapshot_id` are plain, indexed UUID
columns without a database-level foreign key (Postgres requires a
`FOREIGN KEY` to reference a full unique constraint on the parent
table) - referential integrity to `portfolio_valuation_snapshots` is
enforced at the application layer. This is a well-known, documented
TimescaleDB limitation, not an oversight.

Revision ID: 0005_virtual_portfolios
Revises: 0004_historical_market_scenarios
Create Date: 2026-07-19

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005_virtual_portfolios"
down_revision: Union[str, None] = "0004_historical_market_scenarios"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- virtual_portfolios -----------------------------------------------
    op.create_table(
        "virtual_portfolios",
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column("base_currency", sa.String(3), nullable=False),
        sa.Column("initial_cash", sa.Numeric(20, 8), nullable=False),
        sa.Column("cash_balance", sa.Numeric(20, 8), nullable=False),
        sa.Column("benchmark_security_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("allow_fractional_shares", sa.Boolean(), nullable=False),
        sa.Column("require_decision_journal", sa.Boolean(), nullable=False),
        sa.Column("fixed_transaction_fee", sa.Numeric(20, 8), nullable=False),
        sa.Column("transaction_fee_bps", sa.Numeric(10, 4), nullable=False),
        sa.Column("simulation_start_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("current_simulation_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("portfolio_version", sa.String(50), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["learner_id"], ["learner_profiles.learner_id"], name="fk_virtual_portfolios_learner_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["benchmark_security_id"], ["securities.security_id"],
            name="fk_virtual_portfolios_benchmark_security_id", ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_virtual_portfolios_learner_status", "virtual_portfolios", ["learner_id", "status"]
    )
    op.create_index(
        "ix_virtual_portfolios_current_simulation_at", "virtual_portfolios", ["current_simulation_at"]
    )

    # -- portfolio_transactions -----------------------------------------------
    op.create_table(
        "portfolio_transactions",
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("security_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_type", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("requested_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("executed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("requested_quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("executed_quantity", sa.Numeric(20, 8), nullable=True),
        sa.Column("execution_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("gross_amount", sa.Numeric(20, 8), nullable=True),
        sa.Column("fee_amount", sa.Numeric(20, 8), nullable=True),
        sa.Column("net_cash_effect", sa.Numeric(20, 8), nullable=True),
        sa.Column("source_name", sa.String(250), nullable=False),
        sa.Column("interval", sa.String(20), nullable=False),
        sa.Column("execution_rule_version", sa.String(50), nullable=False),
        sa.Column("idempotency_key", sa.String(250), nullable=False),
        sa.Column("rejection_reason", sa.String(50), nullable=True),
        sa.Column("rejection_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["virtual_portfolios.portfolio_id"],
            name="fk_portfolio_transactions_portfolio_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["security_id"], ["securities.security_id"], name="fk_portfolio_transactions_security_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "portfolio_id", "idempotency_key", name="uq_portfolio_transactions_idempotency"
        ),
    )
    op.create_index(
        "ix_portfolio_transactions_portfolio_requested",
        "portfolio_transactions",
        ["portfolio_id", "requested_at"],
    )
    op.create_index(
        "ix_portfolio_transactions_security_executed",
        "portfolio_transactions",
        ["security_id", "executed_at"],
    )
    op.create_index("ix_portfolio_transactions_status", "portfolio_transactions", ["status"])

    # -- portfolio_holdings -----------------------------------------------
    op.create_table(
        "portfolio_holdings",
        sa.Column("holding_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("security_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("average_cost", sa.Numeric(20, 8), nullable=False),
        sa.Column("cost_basis", sa.Numeric(20, 8), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("first_acquired_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_transaction_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["virtual_portfolios.portfolio_id"], name="fk_portfolio_holdings_portfolio_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["security_id"], ["securities.security_id"], name="fk_portfolio_holdings_security_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "portfolio_id", "security_id", name="uq_portfolio_holdings_portfolio_security"
        ),
    )
    op.create_index("ix_portfolio_holdings_portfolio_id", "portfolio_holdings", ["portfolio_id"])
    op.create_index("ix_portfolio_holdings_updated_at", "portfolio_holdings", ["updated_at"])

    # -- portfolio_decision_journal_entries -----------------------------------------------
    op.create_table(
        "portfolio_decision_journal_entries",
        sa.Column("journal_entry_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("security_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("related_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("decision_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("expected_horizon_days", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.String(20), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["virtual_portfolios.portfolio_id"], name="fk_portfolio_journal_portfolio_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"], ["learner_profiles.learner_id"], name="fk_portfolio_journal_learner_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["security_id"], ["securities.security_id"], name="fk_portfolio_journal_security_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["related_transaction_id"], ["portfolio_transactions.transaction_id"],
            name="fk_portfolio_journal_related_transaction_id", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "related_transaction_id", name="uq_portfolio_journal_related_transaction"
        ),
    )
    op.create_index(
        "ix_portfolio_journal_portfolio_decision_at",
        "portfolio_decision_journal_entries",
        ["portfolio_id", "decision_at"],
    )
    op.create_index(
        "ix_portfolio_journal_learner_decision_at",
        "portfolio_decision_journal_entries",
        ["learner_id", "decision_at"],
    )
    op.create_index("ix_portfolio_journal_action", "portfolio_decision_journal_entries", ["action"])
    op.create_index(
        "ix_portfolio_journal_confidence", "portfolio_decision_journal_entries", ["confidence"]
    )

    # -- portfolio_decision_journal_risk_tags (association) -----------------------------------------------
    op.create_table(
        "portfolio_decision_journal_risk_tags",
        sa.Column("journal_entry_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("risk_tag", sa.String(100), primary_key=True),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"], ["portfolio_decision_journal_entries.journal_entry_id"],
            name="fk_portfolio_journal_risk_tags_entry", ondelete="CASCADE",
        ),
    )

    # -- portfolio_decision_journal_information_items (association) -----------------------------------------------
    op.create_table(
        "portfolio_decision_journal_information_items",
        sa.Column("journal_entry_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("information_item", sa.String(500), primary_key=True),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"], ["portfolio_decision_journal_entries.journal_entry_id"],
            name="fk_portfolio_journal_information_items_entry", ondelete="CASCADE",
        ),
    )

    # -- portfolio_decision_journal_assumptions (association) -----------------------------------------------
    op.create_table(
        "portfolio_decision_journal_assumptions",
        sa.Column("journal_entry_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("assumption", sa.String(500), primary_key=True),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"], ["portfolio_decision_journal_entries.journal_entry_id"],
            name="fk_portfolio_journal_assumptions_entry", ondelete="CASCADE",
        ),
    )

    # -- portfolio_valuation_snapshots (hypertable) -----------------------------------------------
    op.create_table(
        "portfolio_valuation_snapshots",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("as_of", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("data_cutoff_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("cash_balance", sa.Numeric(20, 8), nullable=False),
        sa.Column("holdings_value", sa.Numeric(20, 8), nullable=False),
        sa.Column("total_value", sa.Numeric(20, 8), nullable=False),
        sa.Column("total_cost_basis", sa.Numeric(20, 8), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("net_profit", sa.Numeric(20, 8), nullable=False),
        sa.Column("total_return", sa.Numeric(12, 6), nullable=False),
        sa.Column("benchmark_return", sa.Numeric(12, 6), nullable=True),
        sa.Column("excess_return", sa.Numeric(12, 6), nullable=True),
        sa.Column("largest_position_weight", sa.Numeric(6, 4), nullable=False),
        sa.Column("largest_sector_weight", sa.Numeric(6, 4), nullable=True),
        sa.Column("cash_weight", sa.Numeric(6, 4), nullable=False),
        sa.Column("position_count", sa.Integer(), nullable=False),
        sa.Column("portfolio_hhi", sa.Numeric(6, 4), nullable=False),
        sa.Column("sector_hhi", sa.Numeric(6, 4), nullable=True),
        sa.Column("diversification_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("valuation_version", sa.String(50), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["virtual_portfolios.portfolio_id"],
            name="fk_portfolio_valuation_snapshots_portfolio_id", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("snapshot_id", "as_of", name="pk_portfolio_valuation_snapshots"),
        sa.UniqueConstraint(
            "portfolio_id", "as_of", "valuation_version",
            name="uq_portfolio_valuation_snapshots_portfolio_as_of_version",
        ),
    )
    op.create_index(
        "ix_portfolio_valuation_snapshots_portfolio_as_of",
        "portfolio_valuation_snapshots",
        ["portfolio_id", "as_of"],
    )
    op.create_index(
        "ix_portfolio_valuation_snapshots_valuation_version",
        "portfolio_valuation_snapshots",
        ["valuation_version"],
    )
    # Convert to a TimescaleDB hypertable partitioned by `as_of`. The
    # primary key above already includes `as_of`, which TimescaleDB
    # requires of every unique/primary-key constraint on a hypertable.
    op.execute(
        "SELECT create_hypertable('portfolio_valuation_snapshots', 'as_of', if_not_exists => TRUE);"
    )

    # -- portfolio_position_valuations -----------------------------------------------
    op.create_table(
        "portfolio_position_valuations",
        sa.Column("position_valuation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        # `snapshot_id` intentionally has no foreign key - see module docstring above.
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("security_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("market_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("market_value", sa.Numeric(20, 8), nullable=False),
        sa.Column("average_cost", sa.Numeric(20, 8), nullable=False),
        sa.Column("cost_basis", sa.Numeric(20, 8), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("unrealized_return", sa.Numeric(12, 6), nullable=False),
        sa.Column("portfolio_weight", sa.Numeric(6, 4), nullable=False),
        sa.Column("sector", sa.String(250), nullable=True),
        sa.Column("price_timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["virtual_portfolios.portfolio_id"],
            name="fk_portfolio_position_valuations_portfolio_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["security_id"], ["securities.security_id"], name="fk_portfolio_position_valuations_security_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "snapshot_id", "security_id", name="uq_portfolio_position_valuations_snapshot_security"
        ),
    )
    op.create_index(
        "ix_portfolio_position_valuations_snapshot_id", "portfolio_position_valuations", ["snapshot_id"]
    )
    op.create_index(
        "ix_portfolio_position_valuations_portfolio_id", "portfolio_position_valuations", ["portfolio_id"]
    )

    # -- portfolio_risk_assessments -----------------------------------------------
    op.create_table(
        "portfolio_risk_assessments",
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=False),
        # `snapshot_id` intentionally has no foreign key - see module docstring above.
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("risk_level", sa.String(20), nullable=False),
        sa.Column("position_concentration_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("sector_concentration_score", sa.Numeric(6, 4), nullable=True),
        sa.Column("diversification_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("drawdown_risk_score", sa.Numeric(6, 4), nullable=True),
        sa.Column("volatility_risk_score", sa.Numeric(6, 4), nullable=True),
        sa.Column("turnover_risk_score", sa.Numeric(6, 4), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "educational_feedback", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column("policy_version", sa.String(50), nullable=False),
        sa.Column(
            "calculated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["virtual_portfolios.portfolio_id"],
            name="fk_portfolio_risk_assessments_portfolio_id", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "snapshot_id", "policy_version", name="uq_portfolio_risk_assessments_snapshot_version"
        ),
    )
    op.create_index(
        "ix_portfolio_risk_assessments_portfolio_id", "portfolio_risk_assessments", ["portfolio_id"]
    )
    op.create_index(
        "ix_portfolio_risk_assessments_risk_level", "portfolio_risk_assessments", ["risk_level"]
    )

    # -- portfolio_risk_assessment_feedback_codes (association) -----------------------------------------------
    op.create_table(
        "portfolio_risk_assessment_feedback_codes",
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("feedback_code", sa.String(50), primary_key=True),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["portfolio_risk_assessments.assessment_id"],
            name="fk_portfolio_risk_feedback_codes_assessment", ondelete="CASCADE",
        ),
    )

    # -- portfolio_risk_assessment_skills (association) -----------------------------------------------
    op.create_table(
        "portfolio_risk_assessment_skills",
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["portfolio_risk_assessments.assessment_id"],
            name="fk_portfolio_risk_skills_assessment", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["financial_skills.skill_id"], name="fk_portfolio_risk_skills_skill",
            ondelete="RESTRICT",
        ),
    )

    # -- portfolio_valuation_runs -----------------------------------------------
    op.create_table(
        "portfolio_valuation_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("requested_as_of", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("valuation_version", sa.String(50), nullable=False),
        sa.Column("risk_policy_version", sa.String(50), nullable=False),
        sa.Column("holding_count", sa.Integer(), nullable=False),
        sa.Column("priced_holding_count", sa.Integer(), nullable=False),
        sa.Column("missing_price_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_type", sa.String(250), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["virtual_portfolios.portfolio_id"],
            name="fk_portfolio_valuation_runs_portfolio_id", ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_portfolio_valuation_runs_portfolio_started",
        "portfolio_valuation_runs",
        ["portfolio_id", "started_at"],
    )
    op.create_index("ix_portfolio_valuation_runs_status", "portfolio_valuation_runs", ["status"])


def downgrade() -> None:
    op.drop_table("portfolio_valuation_runs")
    op.drop_table("portfolio_risk_assessment_skills")
    op.drop_table("portfolio_risk_assessment_feedback_codes")
    op.drop_table("portfolio_risk_assessments")
    op.drop_table("portfolio_position_valuations")
    op.drop_table("portfolio_valuation_snapshots")
    op.drop_table("portfolio_decision_journal_assumptions")
    op.drop_table("portfolio_decision_journal_information_items")
    op.drop_table("portfolio_decision_journal_risk_tags")
    op.drop_table("portfolio_decision_journal_entries")
    op.drop_table("portfolio_holdings")
    op.drop_table("portfolio_transactions")
    op.drop_table("virtual_portfolios")
