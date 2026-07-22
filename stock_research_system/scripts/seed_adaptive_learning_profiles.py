"""Seed `ExerciseAdaptiveProfile` rows for the "Investing Foundations" curriculum.

Deterministic and idempotent: each profile's ID is derived via
`uuid.uuid5` from the underlying exercise ID, so re-running this script
updates the same rows in place instead of creating duplicates. Requires
`scripts/seed_learning_curriculum.py` to have already run - it loads the
existing curriculum rather than creating exercises itself.

Every lesson in the seeded curriculum has exactly 3 exercises at
positions 0, 1, 2:
    - position 0: diagnostic-eligible AND review-eligible (a quick,
      foundational concept check - the natural first item to probe
      what a learner already knows, and to schedule for later review).
    - position 1: review-eligible only (a slightly deeper check, worth
      revisiting via spaced repetition but not needed to *start* a
      diagnostic).
    - position 2: remediation-eligible (the most involved item in the
      lesson - the one a learner should be routed back to after a
      misconception or a failed attempt).

Since each lesson's position-0 exercise belongs to that lesson's one
primary skill, and every one of the 8 skills has exactly one lesson,
this scheme guarantees every skill has at least one diagnostic-eligible
exercise. With 8 lessons x 3 positions, this yields 8 diagnostic-eligible,
16 review-eligible (positions 0 and 1), and 8 remediation-eligible
(position 2) profiles out of 24 total.

Usage (PowerShell):

    python scripts/seed_adaptive_learning_profiles.py

No investment recommendations and no claims of guaranteed return appear
anywhere in this content.
"""

from __future__ import annotations

import asyncio
import uuid

from stock_research_core.domain.adaptive_learning.models import ExerciseAdaptiveProfile
from stock_research_core.domain.learning.enums import DifficultyLevel, ExerciseType
from stock_research_core.domain.learning.models import Exercise
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

_NAMESPACE = uuid.UUID("f1a4a1e0-2222-4000-8000-000000000000")

_DIFFICULTY_SCORES: dict[DifficultyLevel, float] = {
    DifficultyLevel.BEGINNER: 0.10,
    DifficultyLevel.EASY: 0.30,
    DifficultyLevel.MEDIUM: 0.50,
    DifficultyLevel.HARD: 0.70,
    DifficultyLevel.ADVANCED: 0.90,
}

_ESTIMATED_SECONDS_BY_POSITION: dict[int, int] = {0: 45, 1: 60, 2: 90}


def _profile_id(exercise_id: uuid.UUID) -> uuid.UUID:
    """A stable, deterministic profile UUID derived from the exercise ID."""
    return uuid.uuid5(_NAMESPACE, f"adaptive_profile:{exercise_id}")


def _policy_tags(exercise: Exercise) -> list[str]:
    tags: list[str] = []
    if exercise.position == 0:
        tags.extend(["foundation", "concept-check"])
    elif exercise.position == 1:
        tags.append("review")
    else:
        tags.append("misconception-check")
    if exercise.exercise_type == ExerciseType.NUMERIC_INPUT:
        tags.append("calculation")
    return tags


def _build_profile(exercise: Exercise) -> ExerciseAdaptiveProfile:
    return ExerciseAdaptiveProfile(
        profile_id=_profile_id(exercise.exercise_id),
        exercise_id=exercise.exercise_id,
        base_difficulty_score=_DIFFICULTY_SCORES[exercise.difficulty],
        estimated_seconds=_ESTIMATED_SECONDS_BY_POSITION[exercise.position],
        diagnostic_eligible=exercise.position == 0,
        review_eligible=exercise.position in (0, 1),
        remediation_eligible=exercise.position == 2,
        policy_tags=_policy_tags(exercise),
        active=True,
    )


async def seed() -> None:
    settings = DatabaseSettings()
    engine = create_database_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        uow = SqlAlchemyUnitOfWork(session_factory)

        async with uow:
            paths = await uow.curriculum.list_paths(published_only=False)
            exercises: list[Exercise] = []
            for path in paths:
                for module in await uow.curriculum.list_modules(path.path_id):
                    for lesson in await uow.curriculum.list_lessons(module.module_id):
                        exercises.extend(await uow.curriculum.list_exercises(lesson.lesson_id))

            profiles = [_build_profile(exercise) for exercise in exercises]
            for profile in profiles:
                await uow.adaptive_profiles.upsert(profile)
            await uow.commit()

        diagnostic_count = sum(1 for profile in profiles if profile.diagnostic_eligible)
        review_count = sum(1 for profile in profiles if profile.review_eligible)
        remediation_count = sum(1 for profile in profiles if profile.remediation_eligible)
        print(
            f"Seeded {len(profiles)} adaptive profiles "
            f"({diagnostic_count} diagnostic-eligible, {review_count} review-eligible, "
            f"{remediation_count} remediation-eligible)."
        )
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
