"""Learning core schema: learner profiles, curriculum hierarchy, exercises,
attempts/answers, skill mastery, progress, and misconceptions.

Revision ID: 0002_learning_core
Revises: 0001_initial_schema
Create Date: 2026-07-17

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_learning_core"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- financial_skills -----------------------------------------------
    op.create_table(
        "financial_skills",
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(3000), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("difficulty", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_financial_skills_category", "financial_skills", ["category"])
    op.create_index("ix_financial_skills_active", "financial_skills", ["active"])

    # -- learner_profiles -----------------------------------------------
    op.create_table(
        "learner_profiles",
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("display_name", sa.String(150), nullable=False),
        sa.Column("preferred_language", sa.String(10), nullable=False),
        sa.Column("financial_experience_level", sa.String(20), nullable=False),
        sa.Column("daily_goal_minutes", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # -- learning_paths -----------------------------------------------
    op.create_table(
        "learning_paths",
        sa.Column("path_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False, unique=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(3000), nullable=False),
        sa.Column("difficulty", sa.String(20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_learning_paths_position", "learning_paths", ["position"])

    # -- skill_prerequisites (association) -----------------------------------------------
    op.create_table(
        "skill_prerequisites",
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("prerequisite_skill_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["financial_skills.skill_id"], name="fk_skill_prereq_skill", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["prerequisite_skill_id"],
            ["financial_skills.skill_id"],
            name="fk_skill_prereq_prerequisite",
            ondelete="CASCADE",
        ),
    )

    # -- learning_modules -----------------------------------------------
    op.create_table(
        "learning_modules",
        sa.Column("module_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("path_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(3000), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["path_id"], ["learning_paths.path_id"], name="fk_learning_modules_path_id", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("path_id", "code", name="uq_learning_modules_path_code"),
    )
    op.create_index("ix_learning_modules_path_position", "learning_modules", ["path_id", "position"])

    # -- lessons -----------------------------------------------
    op.create_table(
        "lessons",
        sa.Column("lesson_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.String(2000), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("primary_skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["module_id"], ["learning_modules.module_id"], name="fk_lessons_module_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["primary_skill_id"],
            ["financial_skills.skill_id"],
            name="fk_lessons_primary_skill_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("module_id", "code", name="uq_lessons_module_code"),
    )
    op.create_index("ix_lessons_module_position", "lessons", ["module_id", "position"])
    op.create_index("ix_lessons_primary_skill_id", "lessons", ["primary_skill_id"])

    # -- lesson_secondary_skills (association) -----------------------------------------------
    op.create_table(
        "lesson_secondary_skills",
        sa.Column("lesson_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(
            ["lesson_id"], ["lessons.lesson_id"], name="fk_lesson_secondary_skills_lesson", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["financial_skills.skill_id"],
            name="fk_lesson_secondary_skills_skill",
            ondelete="RESTRICT",
        ),
    )

    # -- exercises -----------------------------------------------
    op.create_table(
        "exercises",
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("lesson_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_type", sa.String(30), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.String(20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("maximum_score", sa.Numeric(10, 4), nullable=False),
        sa.Column("passing_score", sa.Numeric(10, 4), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["lesson_id"], ["lessons.lesson_id"], name="fk_exercises_lesson_id", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_exercises_lesson_position", "exercises", ["lesson_id", "position"])
    op.create_index("ix_exercises_exercise_type", "exercises", ["exercise_type"])

    # -- exercise_skills (association) -----------------------------------------------
    op.create_table(
        "exercise_skills",
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(
            ["exercise_id"], ["exercises.exercise_id"], name="fk_exercise_skills_exercise", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["financial_skills.skill_id"], name="fk_exercise_skills_skill", ondelete="RESTRICT"
        ),
    )

    # -- exercise_options -----------------------------------------------
    op.create_table(
        "exercise_options",
        sa.Column("option_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("option_key", sa.String(50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercises.exercise_id"],
            name="fk_exercise_options_exercise_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("exercise_id", "option_key", name="uq_exercise_options_exercise_key"),
    )
    op.create_index("ix_exercise_options_exercise_position", "exercise_options", ["exercise_id", "position"])

    # -- exercise_attempts -----------------------------------------------
    op.create_table(
        "exercise_attempts",
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("graded_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("score", sa.Numeric(10, 4), nullable=True),
        sa.Column("maximum_score", sa.Numeric(10, 4), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("confidence_level", sa.String(20), nullable=True),
        sa.Column("response_time_seconds", sa.Integer(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learner_profiles.learner_id"],
            name="fk_exercise_attempts_learner_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercises.exercise_id"],
            name="fk_exercise_attempts_exercise_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_exercise_attempts_learner_exercise", "exercise_attempts", ["learner_id", "exercise_id"]
    )
    op.create_index(
        "ix_exercise_attempts_learner_started", "exercise_attempts", ["learner_id", "started_at"]
    )
    op.create_index("ix_exercise_attempts_exercise_id", "exercise_attempts", ["exercise_id"])

    # -- exercise_answers -----------------------------------------------
    op.create_table(
        "exercise_answers",
        sa.Column("answer_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("numeric_answer", sa.Numeric(20, 8), nullable=True),
        sa.Column("text_answer", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["exercise_attempts.attempt_id"],
            name="fk_exercise_answers_attempt_id",
            ondelete="CASCADE",
        ),
    )

    # -- exercise_answer_selected_options (association) -----------------------------------------------
    op.create_table(
        "exercise_answer_selected_options",
        sa.Column("answer_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("option_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(
            ["answer_id"],
            ["exercise_answers.answer_id"],
            name="fk_answer_selected_options_answer",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["option_id"],
            ["exercise_options.option_id"],
            name="fk_answer_selected_options_option",
            ondelete="RESTRICT",
        ),
    )

    # -- exercise_answer_ordered_options (association) -----------------------------------------------
    op.create_table(
        "exercise_answer_ordered_options",
        sa.Column("answer_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("option_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["answer_id"],
            ["exercise_answers.answer_id"],
            name="fk_answer_ordered_options_answer",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["option_id"],
            ["exercise_options.option_id"],
            name="fk_answer_ordered_options_option",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "answer_id", "sequence_index", name="uq_answer_ordered_options_sequence"
        ),
    )

    # -- skill_mastery -----------------------------------------------
    op.create_table(
        "skill_mastery",
        sa.Column("mastery_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mastery_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("mastery_level", sa.String(20), nullable=False),
        sa.Column("correct_attempts", sa.Integer(), nullable=False),
        sa.Column("total_attempts", sa.Integer(), nullable=False),
        sa.Column("consecutive_correct", sa.Integer(), nullable=False),
        sa.Column("last_practiced_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("next_review_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("calculation_version", sa.String(50), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learner_profiles.learner_id"],
            name="fk_skill_mastery_learner_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["financial_skills.skill_id"], name="fk_skill_mastery_skill_id", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("learner_id", "skill_id", name="uq_skill_mastery_learner_skill"),
    )
    op.create_index("ix_skill_mastery_learner_id", "skill_mastery", ["learner_id"])
    op.create_index("ix_skill_mastery_skill_id", "skill_mastery", ["skill_id"])

    # -- user_progress -----------------------------------------------
    op.create_table(
        "user_progress",
        sa.Column("progress_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("path_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lesson_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("completion_percentage", sa.Numeric(5, 2), nullable=False),
        sa.Column("best_score", sa.Numeric(10, 4), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("first_started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learner_profiles.learner_id"],
            name="fk_user_progress_learner_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["path_id"], ["learning_paths.path_id"], name="fk_user_progress_path_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["learning_modules.module_id"],
            name="fk_user_progress_module_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"], ["lessons.lesson_id"], name="fk_user_progress_lesson_id", ondelete="RESTRICT"
        ),
    )
    op.create_index("ix_user_progress_learner_id", "user_progress", ["learner_id"])
    op.create_index("ix_user_progress_status", "user_progress", ["status"])
    # Partial unique indexes: a row targets exactly one granularity, and
    # plain multi-column UNIQUE constraints don't work here because SQL
    # NULL is never equal to NULL (so a normal unique constraint spanning
    # all three nullable FK columns would never actually catch duplicates).
    op.create_index(
        "uq_user_progress_path",
        "user_progress",
        ["learner_id", "path_id"],
        unique=True,
        postgresql_where=sa.text("path_id IS NOT NULL"),
    )
    op.create_index(
        "uq_user_progress_module",
        "user_progress",
        ["learner_id", "module_id"],
        unique=True,
        postgresql_where=sa.text("module_id IS NOT NULL"),
    )
    op.create_index(
        "uq_user_progress_lesson",
        "user_progress",
        ["learner_id", "lesson_id"],
        unique=True,
        postgresql_where=sa.text("lesson_id IS NOT NULL"),
    )

    # -- misconceptions -----------------------------------------------
    op.create_table(
        "misconceptions",
        sa.Column("misconception_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("confidence_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("first_detected_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("detector_version", sa.String(50), nullable=False),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learner_profiles.learner_id"],
            name="fk_misconceptions_learner_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["financial_skills.skill_id"], name="fk_misconceptions_skill_id", ondelete="RESTRICT"
        ),
    )
    op.create_index("ix_misconceptions_learner_id", "misconceptions", ["learner_id"])
    op.create_index("ix_misconceptions_skill_id", "misconceptions", ["skill_id"])
    op.create_index("ix_misconceptions_status", "misconceptions", ["status"])
    op.create_index(
        "uq_misconceptions_active_learner_skill_code",
        "misconceptions",
        ["learner_id", "skill_id", "code"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    # -- misconception_evidence_attempts (association) -----------------------------------------------
    op.create_table(
        "misconception_evidence_attempts",
        sa.Column("misconception_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(
            ["misconception_id"],
            ["misconceptions.misconception_id"],
            name="fk_misconception_evidence_misconception",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["exercise_attempts.attempt_id"],
            name="fk_misconception_evidence_attempt",
            ondelete="RESTRICT",
        ),
    )


def downgrade() -> None:
    op.drop_table("misconception_evidence_attempts")
    op.drop_table("misconceptions")
    op.drop_table("user_progress")
    op.drop_table("skill_mastery")
    op.drop_table("exercise_answer_ordered_options")
    op.drop_table("exercise_answer_selected_options")
    op.drop_table("exercise_answers")
    op.drop_table("exercise_attempts")
    op.drop_table("exercise_options")
    op.drop_table("exercise_skills")
    op.drop_table("exercises")
    op.drop_table("lesson_secondary_skills")
    op.drop_table("lessons")
    op.drop_table("learning_modules")
    op.drop_table("skill_prerequisites")
    op.drop_table("learning_paths")
    op.drop_table("learner_profiles")
    op.drop_table("financial_skills")
