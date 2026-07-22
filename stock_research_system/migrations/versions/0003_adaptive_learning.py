"""Adaptive learning engine schema: exercise adaptive profiles, learning
sessions/activities, diagnostic assessments/items, skill review schedules,
and auditable adaptive decisions.

Revision ID: 0003_adaptive_learning
Revises: 0002_learning_core
Create Date: 2026-07-17

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003_adaptive_learning"
down_revision: Union[str, None] = "0002_learning_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- exercise_adaptive_profiles -----------------------------------------------
    op.create_table(
        "exercise_adaptive_profiles",
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("base_difficulty_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("estimated_seconds", sa.Integer(), nullable=False),
        sa.Column("diagnostic_eligible", sa.Boolean(), nullable=False),
        sa.Column("review_eligible", sa.Boolean(), nullable=False),
        sa.Column("remediation_eligible", sa.Boolean(), nullable=False),
        sa.Column("minimum_mastery_score", sa.Numeric(6, 4), nullable=True),
        sa.Column("maximum_mastery_score", sa.Numeric(6, 4), nullable=True),
        sa.Column(
            "recommended_prerequisite_skill_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
        ),
        sa.Column("policy_tags", postgresql.ARRAY(sa.String(50)), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercises.exercise_id"],
            name="fk_exercise_adaptive_profiles_exercise_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_exercise_adaptive_profiles_active", "exercise_adaptive_profiles", ["active"])
    op.create_index(
        "ix_exercise_adaptive_profiles_diagnostic_eligible",
        "exercise_adaptive_profiles",
        ["diagnostic_eligible"],
    )
    op.create_index(
        "ix_exercise_adaptive_profiles_review_eligible", "exercise_adaptive_profiles", ["review_eligible"]
    )

    # -- learning_sessions -----------------------------------------------
    op.create_table(
        "learning_sessions",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("goal_minutes", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("abandoned_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("recommended_item_count", sa.Integer(), nullable=False),
        sa.Column("completed_item_count", sa.Integer(), nullable=False),
        sa.Column("correct_item_count", sa.Integer(), nullable=False),
        sa.Column("total_score", sa.Numeric(10, 4), nullable=False),
        sa.Column("maximum_score", sa.Numeric(10, 4), nullable=False),
        sa.Column("policy_version", sa.String(50), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learner_profiles.learner_id"],
            name="fk_learning_sessions_learner_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_learning_sessions_status", "learning_sessions", ["status"])
    op.create_index("ix_learning_sessions_session_type", "learning_sessions", ["session_type"])
    op.create_index(
        "ix_learning_sessions_learner_status", "learning_sessions", ["learner_id", "status"]
    )
    op.create_index("ix_learning_sessions_started_at", "learning_sessions", ["started_at"])

    # -- diagnostic_assessments -----------------------------------------------
    op.create_table(
        "diagnostic_assessments",
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("maximum_items", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("policy_version", sa.String(50), nullable=False),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learner_profiles.learner_id"],
            name="fk_diagnostic_assessments_learner_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_diagnostic_assessments_status", "diagnostic_assessments", ["status"])
    op.create_index(
        "ix_diagnostic_assessments_learner_created", "diagnostic_assessments", ["learner_id", "created_at"]
    )

    # -- diagnostic_assessment_skills (association) -----------------------------------------------
    op.create_table(
        "diagnostic_assessment_skills",
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["diagnostic_assessments.assessment_id"],
            name="fk_diagnostic_assessment_skills_assessment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["financial_skills.skill_id"],
            name="fk_diagnostic_assessment_skills_skill",
            ondelete="RESTRICT",
        ),
    )

    # -- diagnostic_assessment_items -----------------------------------------------
    op.create_table(
        "diagnostic_assessment_items",
        sa.Column("item_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("selected_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("normalized_score", sa.Numeric(6, 4), nullable=True),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["diagnostic_assessments.assessment_id"],
            name="fk_diagnostic_items_assessment_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercises.exercise_id"],
            name="fk_diagnostic_items_exercise_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["exercise_attempts.attempt_id"],
            name="fk_diagnostic_items_attempt_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "assessment_id", "position", name="uq_diagnostic_items_assessment_position"
        ),
        sa.UniqueConstraint(
            "assessment_id", "exercise_id", name="uq_diagnostic_items_assessment_exercise"
        ),
    )
    op.create_index(
        "ix_diagnostic_items_assessment_id", "diagnostic_assessment_items", ["assessment_id"]
    )

    # -- diagnostic_item_skills (association) -----------------------------------------------
    op.create_table(
        "diagnostic_item_skills",
        sa.Column("item_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["diagnostic_assessment_items.item_id"],
            name="fk_diagnostic_item_skills_item",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["financial_skills.skill_id"],
            name="fk_diagnostic_item_skills_skill",
            ondelete="RESTRICT",
        ),
    )

    # -- skill_review_schedules -----------------------------------------------
    op.create_table(
        "skill_review_schedules",
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("last_reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("next_review_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("review_interval_days", sa.Integer(), nullable=False),
        sa.Column("successful_review_count", sa.Integer(), nullable=False),
        sa.Column("failed_review_count", sa.Integer(), nullable=False),
        sa.Column("consecutive_successful_reviews", sa.Integer(), nullable=False),
        sa.Column("ease_factor", sa.Numeric(3, 2), nullable=False),
        sa.Column("calculation_version", sa.String(50), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learner_profiles.learner_id"],
            name="fk_skill_review_schedules_learner_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["financial_skills.skill_id"],
            name="fk_skill_review_schedules_skill_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("learner_id", "skill_id", name="uq_review_schedules_learner_skill"),
    )
    op.create_index(
        "ix_review_schedules_next_review_at", "skill_review_schedules", ["next_review_at"]
    )
    op.create_index(
        "ix_review_schedules_learner_status", "skill_review_schedules", ["learner_id", "status"]
    )

    # -- adaptive_decisions -----------------------------------------------
    op.create_table(
        "adaptive_decisions",
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recommendation_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("recommended_exercise_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recommended_lesson_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("priority_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("recommended_difficulty_score", sa.Numeric(6, 4), nullable=True),
        sa.Column("policy_version", sa.String(50), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("generated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("accepted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("skipped_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learner_profiles.learner_id"],
            name="fk_adaptive_decisions_learner_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["learning_sessions.session_id"],
            name="fk_adaptive_decisions_session_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recommended_exercise_id"],
            ["exercises.exercise_id"],
            name="fk_adaptive_decisions_exercise_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recommended_lesson_id"],
            ["lessons.lesson_id"],
            name="fk_adaptive_decisions_lesson_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_adaptive_decisions_recommendation_type", "adaptive_decisions", ["recommendation_type"]
    )
    op.create_index("ix_adaptive_decisions_status", "adaptive_decisions", ["status"])
    op.create_index(
        "ix_adaptive_decisions_learner_generated", "adaptive_decisions", ["learner_id", "generated_at"]
    )
    op.create_index(
        "ix_adaptive_decisions_session_generated", "adaptive_decisions", ["session_id", "generated_at"]
    )

    # -- adaptive_decision_target_skills (association) -----------------------------------------------
    op.create_table(
        "adaptive_decision_target_skills",
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["adaptive_decisions.decision_id"],
            name="fk_adaptive_decision_target_skills_decision",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["financial_skills.skill_id"],
            name="fk_adaptive_decision_target_skills_skill",
            ondelete="RESTRICT",
        ),
    )

    # -- adaptive_decision_reasons (association) -----------------------------------------------
    op.create_table(
        "adaptive_decision_reasons",
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("reason_code", sa.String(40), primary_key=True),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["adaptive_decisions.decision_id"],
            name="fk_adaptive_decision_reasons_decision",
            ondelete="CASCADE",
        ),
    )

    # -- learning_session_activities -----------------------------------------------
    op.create_table(
        "learning_session_activities",
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("recommended_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("skipped_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["learning_sessions.session_id"],
            name="fk_session_activities_session_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learner_profiles.learner_id"],
            name="fk_session_activities_learner_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercises.exercise_id"],
            name="fk_session_activities_exercise_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["exercise_attempts.attempt_id"],
            name="fk_session_activities_attempt_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["adaptive_decisions.decision_id"],
            name="fk_session_activities_decision_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("session_id", "position", name="uq_session_activities_session_position"),
    )
    op.create_index(
        "ix_session_activities_session_id", "learning_session_activities", ["session_id"]
    )
    op.create_index(
        "ix_session_activities_learner_id", "learning_session_activities", ["learner_id"]
    )
    op.create_index(
        "ix_session_activities_exercise_id", "learning_session_activities", ["exercise_id"]
    )


def downgrade() -> None:
    op.drop_table("learning_session_activities")
    op.drop_table("adaptive_decision_reasons")
    op.drop_table("adaptive_decision_target_skills")
    op.drop_table("adaptive_decisions")
    op.drop_table("skill_review_schedules")
    op.drop_table("diagnostic_item_skills")
    op.drop_table("diagnostic_assessment_items")
    op.drop_table("diagnostic_assessment_skills")
    op.drop_table("diagnostic_assessments")
    op.drop_table("learning_sessions")
    op.drop_table("exercise_adaptive_profiles")
