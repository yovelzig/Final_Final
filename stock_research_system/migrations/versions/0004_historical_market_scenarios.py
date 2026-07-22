"""Historical market scenario engine schema: scenarios, securities,
option rubrics, outcomes, submissions, and generation-run audit
records. Also adds a nullable `grading_version` column to the existing
`exercise_attempts` table (see `application.learning.service.
LearningService.submit_externally_graded_answer`).

Revision ID: 0004_historical_market_scenarios
Revises: 0003_adaptive_learning
Create Date: 2026-07-17

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004_historical_market_scenarios"
down_revision: Union[str, None] = "0003_adaptive_learning"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("exercise_attempts", sa.Column("grading_version", sa.String(50), nullable=True))

    # -- historical_market_scenarios -----------------------------------------------
    op.create_table(
        "historical_market_scenarios",
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(150), nullable=False),
        sa.Column("title", sa.String(250), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("scenario_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("observation_start_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("decision_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("reveal_end_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("interval", sa.String(20), nullable=False),
        sa.Column("source_name", sa.String(250), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("learner_instructions", sa.Text(), nullable=False),
        sa.Column("learning_objectives", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("minimum_observation_bars", sa.Integer(), nullable=False),
        sa.Column("minimum_reveal_bars", sa.Integer(), nullable=False),
        sa.Column("scenario_version", sa.String(50), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercises.exercise_id"],
            name="fk_historical_market_scenarios_exercise_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("code", name="uq_historical_market_scenarios_code"),
        sa.UniqueConstraint("exercise_id", name="uq_historical_market_scenarios_exercise_id"),
        sa.CheckConstraint(
            "observation_start_at < decision_at AND decision_at < reveal_end_at",
            name="ck_historical_market_scenarios_timestamp_order",
        ),
        sa.CheckConstraint(
            "minimum_observation_bars >= 5", name="ck_historical_market_scenarios_min_observation_bars"
        ),
        sa.CheckConstraint(
            "minimum_reveal_bars >= 1", name="ck_historical_market_scenarios_min_reveal_bars"
        ),
    )
    op.create_index(
        "ix_historical_market_scenarios_scenario_type",
        "historical_market_scenarios",
        ["scenario_type"],
    )
    op.create_index(
        "ix_historical_market_scenarios_status", "historical_market_scenarios", ["status"]
    )

    # -- historical_market_scenario_primary_skills (association) -----------------------------------------------
    op.create_table(
        "historical_market_scenario_primary_skills",
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["historical_market_scenarios.scenario_id"],
            name="fk_scenario_primary_skills_scenario",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["financial_skills.skill_id"],
            name="fk_scenario_primary_skills_skill",
            ondelete="RESTRICT",
        ),
    )

    # -- historical_market_scenario_secondary_skills (association) -----------------------------------------------
    op.create_table(
        "historical_market_scenario_secondary_skills",
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["historical_market_scenarios.scenario_id"],
            name="fk_scenario_secondary_skills_scenario",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["financial_skills.skill_id"],
            name="fk_scenario_secondary_skills_skill",
            ondelete="RESTRICT",
        ),
    )

    # -- scenario_securities -----------------------------------------------
    op.create_table(
        "scenario_securities",
        sa.Column("scenario_security_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("security_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["historical_market_scenarios.scenario_id"],
            name="fk_scenario_securities_scenario_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["security_id"],
            ["securities.security_id"],
            name="fk_scenario_securities_security_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("scenario_id", "role", name="uq_scenario_securities_scenario_role"),
        sa.UniqueConstraint(
            "scenario_id", "security_id", name="uq_scenario_securities_scenario_security"
        ),
        sa.CheckConstraint("role IN ('FOCAL', 'BENCHMARK')", name="ck_scenario_securities_role"),
    )

    # -- scenario_option_rubrics -----------------------------------------------
    _score_columns = (
        "decision_quality_score",
        "risk_awareness_score",
        "benchmark_awareness_score",
        "horizon_alignment_score",
        "information_sufficiency_score",
        "uncertainty_awareness_score",
    )
    op.create_table(
        "scenario_option_rubrics",
        sa.Column("rubric_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_option_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision_quality_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("risk_awareness_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("benchmark_awareness_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("horizon_alignment_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("information_sufficiency_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("uncertainty_awareness_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("expected_direction", sa.String(30), nullable=False),
        sa.Column("positive_feedback", sa.Text(), nullable=False),
        sa.Column("improvement_feedback", sa.Text(), nullable=False),
        sa.Column("rubric_version", sa.String(50), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["historical_market_scenarios.scenario_id"],
            name="fk_scenario_option_rubrics_scenario_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exercise_option_id"],
            ["exercise_options.option_id"],
            name="fk_scenario_option_rubrics_option_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "scenario_id",
            "exercise_option_id",
            "rubric_version",
            name="uq_scenario_option_rubrics_scenario_option_version",
        ),
        *(
            sa.CheckConstraint(
                f"{column} >= 0 AND {column} <= 1", name=f"ck_scenario_option_rubrics_{column}_range"
            )
            for column in _score_columns
        ),
    )

    # -- scenario_option_rubric_feedback_codes (association) -----------------------------------------------
    op.create_table(
        "scenario_option_rubric_feedback_codes",
        sa.Column("rubric_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("feedback_code", sa.String(40), primary_key=True),
        sa.ForeignKeyConstraint(
            ["rubric_id"],
            ["scenario_option_rubrics.rubric_id"],
            name="fk_scenario_rubric_feedback_codes_rubric",
            ondelete="CASCADE",
        ),
    )

    # -- scenario_outcomes -----------------------------------------------
    op.create_table(
        "scenario_outcomes",
        sa.Column("outcome_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("reveal_end_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("focal_start_close", sa.Numeric(20, 8), nullable=False),
        sa.Column("focal_end_close", sa.Numeric(20, 8), nullable=False),
        sa.Column("focal_return", sa.Numeric(12, 6), nullable=False),
        sa.Column("maximum_future_upside", sa.Numeric(12, 6), nullable=False),
        sa.Column("maximum_future_drawdown", sa.Numeric(12, 6), nullable=False),
        sa.Column("benchmark_return", sa.Numeric(12, 6), nullable=True),
        sa.Column("excess_return", sa.Numeric(12, 6), nullable=True),
        sa.Column("outcome_direction", sa.String(20), nullable=False),
        sa.Column("outcome_summary", sa.Text(), nullable=False),
        sa.Column("calculation_version", sa.String(50), nullable=False),
        sa.Column(
            "calculated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["historical_market_scenarios.scenario_id"],
            name="fk_scenario_outcomes_scenario_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "scenario_id", "calculation_version", name="uq_scenario_outcomes_scenario_version"
        ),
        sa.CheckConstraint(
            "maximum_future_upside >= 0", name="ck_scenario_outcomes_max_upside_nonneg"
        ),
        sa.CheckConstraint(
            "maximum_future_drawdown <= 0", name="ck_scenario_outcomes_max_drawdown_nonpos"
        ),
    )

    # -- scenario_submissions -----------------------------------------------
    op.create_table(
        "scenario_submissions",
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("selected_option_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("confidence_level", sa.String(20), nullable=True),
        sa.Column("learner_rationale", sa.Text(), nullable=True),
        sa.Column("decision_quality_score", sa.Numeric(6, 4), nullable=True),
        sa.Column("outcome_alignment_score", sa.Numeric(6, 4), nullable=True),
        sa.Column("total_display_score", sa.Numeric(6, 4), nullable=True),
        sa.Column("decision_quality", sa.String(20), nullable=True),
        sa.Column("feedback_text", sa.Text(), nullable=True),
        sa.Column("reveal_status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("graded_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revealed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("rubric_version", sa.String(50), nullable=False),
        sa.Column("outcome_calculation_version", sa.String(50), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["historical_market_scenarios.scenario_id"],
            name="fk_scenario_submissions_scenario_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learner_profiles.learner_id"],
            name="fk_scenario_submissions_learner_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["exercise_attempt_id"],
            ["exercise_attempts.attempt_id"],
            name="fk_scenario_submissions_attempt_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["selected_option_id"],
            ["exercise_options.option_id"],
            name="fk_scenario_submissions_option_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "exercise_attempt_id", name="uq_scenario_submissions_exercise_attempt_id"
        ),
    )
    op.create_index(
        "ix_scenario_submissions_learner_created",
        "scenario_submissions",
        ["learner_id", "created_at"],
    )
    op.create_index(
        "ix_scenario_submissions_scenario_created",
        "scenario_submissions",
        ["scenario_id", "created_at"],
    )

    # -- scenario_submission_feedback_codes (association) -----------------------------------------------
    op.create_table(
        "scenario_submission_feedback_codes",
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("feedback_code", sa.String(40), primary_key=True),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["scenario_submissions.submission_id"],
            name="fk_scenario_submission_feedback_codes_submission",
            ondelete="CASCADE",
        ),
    )

    # -- scenario_generation_runs -----------------------------------------------
    op.create_table(
        "scenario_generation_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("focal_security_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("benchmark_security_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requested_observation_start_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("requested_decision_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("requested_reveal_end_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("scenario_code", sa.String(150), nullable=False),
        sa.Column("scenario_version", sa.String(50), nullable=False),
        sa.Column("observation_bars_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reveal_bars_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("benchmark_bars_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_type", sa.String(200), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["focal_security_id"],
            ["securities.security_id"],
            name="fk_scenario_generation_runs_focal_security",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["benchmark_security_id"],
            ["securities.security_id"],
            name="fk_scenario_generation_runs_benchmark_security",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_scenario_generation_runs_status", "scenario_generation_runs", ["status"]
    )
    op.create_index(
        "ix_scenario_generation_runs_started_at", "scenario_generation_runs", ["started_at"]
    )


def downgrade() -> None:
    op.drop_table("scenario_generation_runs")
    op.drop_table("scenario_submission_feedback_codes")
    op.drop_table("scenario_submissions")
    op.drop_table("scenario_outcomes")
    op.drop_table("scenario_option_rubric_feedback_codes")
    op.drop_table("scenario_option_rubrics")
    op.drop_table("scenario_securities")
    op.drop_table("historical_market_scenario_secondary_skills")
    op.drop_table("historical_market_scenario_primary_skills")
    op.drop_table("historical_market_scenarios")
    op.drop_column("exercise_attempts", "grading_version")
