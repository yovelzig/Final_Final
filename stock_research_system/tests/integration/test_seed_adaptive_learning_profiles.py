"""PostgreSQL integration tests: scripts/seed_adaptive_learning_profiles.py.

Verifies the deterministic seeded 24-profile subtree only, and — this is
the regression test for the scope-defect correction made in Phase B
checkpoint B3 — proves the adaptive-profile seed no longer creates a
profile for any exercise outside the seeded "Investing Foundations"
path. `EXPECTED_EXERCISE_KEYS` is an independent, hard-coded oracle
(copied from the same source-of-truth as
`test_seed_learning_curriculum.py`, but not imported from it and not
derived from the production `MODULES` constant), so this file has no
dependency on that other test file or on a third shared helper module.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from scripts.seed_adaptive_learning_profiles import (
    _DIFFICULTY_SCORES,
    _profile_id,
    seed as seed_adaptive_profiles,
)
from scripts.seed_learning_curriculum import _id, seed as seed_curriculum
from stock_research_core.domain.learning.enums import (
    DifficultyLevel,
    ExerciseType,
    FinancialSkillCategory,
    LessonStatus,
)
from stock_research_core.domain.learning.models import (
    Exercise,
    LearningModule,
    LearningPath,
    Lesson,
    Skill,
)
from stock_research_core.infrastructure.database.config import DatabaseSettings

pytestmark = pytest.mark.integration

EXPECTED_EXERCISE_KEYS = [
    "money-functions-single-choice",
    "money-store-of-value-true-false",
    "money-functions-multiple-choice",
    "inflation-definition-single-choice",
    "inflation-rule-of-72-numeric",
    "inflation-purchasing-power-true-false",
    "stock-ownership-single-choice",
    "stock-benefit-true-false",
    "stock-price-factors-multiple-choice",
    "bond-definition-single-choice",
    "etf-definition-single-choice",
    "fund-exposure-true-false",
    "risk-return-relationship-single-choice",
    "diversification-guarantee-true-false",
    "return-percentage-numeric",
    "simple-vs-compound-single-choice",
    "simple-interest-numeric",
    "compound-growth-ordering",
    "most-diversified-portfolio-single-choice",
    "diversification-guarantee-true-false-2",
    "diversification-examples-multiple-choice",
    "concentration-risk-definition-single-choice",
    "concentration-vs-spread-true-false",
    "equal-split-percentage-numeric",
]

SEEDED_EXERCISE_IDS = {_id(f"exercise:{key}") for key in EXPECTED_EXERCISE_KEYS}


@pytest.fixture(autouse=True)
def _seed_scripts_use_test_database(
    monkeypatch: pytest.MonkeyPatch,
    database_settings: DatabaseSettings,
) -> None:
    assert database_settings.test_database_url is not None
    monkeypatch.setenv("DATABASE_URL", database_settings.test_database_url)


async def _seed_unrelated_exercise(uow_factory) -> Exercise:
    """Create one unrelated, published path/module/lesson/exercise chain.

    Mirrors `test_adaptive_profile_repository.py`'s `_seed_exercise`
    helper, but with an explicit, distinct natural code on every level
    so it can never collide with the deterministic "investing-foundations"
    subtree.
    """
    suffix = uuid4().hex[:8]
    skill = Skill(
        code=f"UNRELATED_SKILL_{suffix.upper()}",
        name="Unrelated Skill",
        description="An unrelated skill outside the seeded curriculum.",
        category=FinancialSkillCategory.MONEY_BASICS,
        difficulty=DifficultyLevel.BEGINNER,
    )
    async with uow_factory() as uow:
        stored_skill = await uow.curriculum.upsert_skill(skill)
        path = await uow.curriculum.upsert_path(
            LearningPath(
                code=f"unrelated-{suffix}",
                title="Unrelated Path",
                description="An unrelated path outside the seeded curriculum.",
                difficulty=DifficultyLevel.BEGINNER,
                position=0,
                estimated_minutes=10,
                published=True,
            )
        )
        module = await uow.curriculum.upsert_module(
            LearningModule(
                path_id=path.path_id,
                code=f"unrelated-module-{suffix}",
                title="Unrelated Module",
                description="An unrelated module.",
                position=0,
                estimated_minutes=10,
                published=True,
            )
        )
        lesson = await uow.curriculum.upsert_lesson(
            Lesson(
                module_id=module.module_id,
                code=f"unrelated-lesson-{suffix}",
                title="Unrelated Lesson",
                summary="An unrelated lesson.",
                content_markdown="# Unrelated",
                difficulty=DifficultyLevel.BEGINNER,
                status=LessonStatus.PUBLISHED,
                position=0,
                estimated_minutes=10,
                primary_skill_id=stored_skill.skill_id,
            )
        )
        exercise = Exercise(
            lesson_id=lesson.lesson_id,
            exercise_type=ExerciseType.SINGLE_CHOICE,
            prompt="An unrelated prompt.",
            explanation="An unrelated explanation.",
            difficulty=DifficultyLevel.BEGINNER,
            position=0,
            skill_ids=[stored_skill.skill_id],
            maximum_score=1.0,
            passing_score=1.0,
        )
        stored_exercise = await uow.curriculum.upsert_exercise(exercise)
        await uow.commit()
    return stored_exercise


async def test_adaptive_seed_without_target_curriculum_is_safe_zero_op(uow_factory) -> None:
    await seed_adaptive_profiles()

    async with uow_factory() as uow:
        profiles = await uow.adaptive_profiles.list_active()
        assert profiles == []


async def test_adaptive_seed_creates_exact_profiles_for_seeded_exercises(uow_factory) -> None:
    await seed_curriculum()
    await seed_adaptive_profiles()

    diagnostic_count = 0
    review_count = 0
    remediation_count = 0
    async with uow_factory() as uow:
        for exercise_id in SEEDED_EXERCISE_IDS:
            profile = await uow.adaptive_profiles.get_by_exercise(exercise_id)
            assert profile is not None
            assert profile.profile_id == _profile_id(exercise_id)
            if profile.diagnostic_eligible:
                diagnostic_count += 1
            if profile.review_eligible:
                review_count += 1
            if profile.remediation_eligible:
                remediation_count += 1

    assert diagnostic_count == 8
    assert review_count == 16
    assert remediation_count == 8


async def test_adaptive_seed_ignores_unrelated_curriculum(uow_factory) -> None:
    await seed_curriculum()
    unrelated_exercise = await _seed_unrelated_exercise(uow_factory)

    await seed_adaptive_profiles()

    async with uow_factory() as uow:
        for exercise_id in SEEDED_EXERCISE_IDS:
            profile = await uow.adaptive_profiles.get_by_exercise(exercise_id)
            assert profile is not None

        unrelated_profile = await uow.adaptive_profiles.get_by_exercise(
            unrelated_exercise.exercise_id
        )
        assert unrelated_profile is None

    await seed_adaptive_profiles()

    async with uow_factory() as uow:
        unrelated_profile_after_rerun = await uow.adaptive_profiles.get_by_exercise(
            unrelated_exercise.exercise_id
        )
        assert unrelated_profile_after_rerun is None


async def test_adaptive_seed_rerun_is_idempotent_and_preserves_ids(uow_factory) -> None:
    await seed_curriculum()
    await seed_adaptive_profiles()

    async with uow_factory() as uow:
        first_ids = {
            exercise_id: (await uow.adaptive_profiles.get_by_exercise(exercise_id)).profile_id
            for exercise_id in SEEDED_EXERCISE_IDS
        }

    await seed_adaptive_profiles()

    async with uow_factory() as uow:
        second_ids = {
            exercise_id: (await uow.adaptive_profiles.get_by_exercise(exercise_id)).profile_id
            for exercise_id in SEEDED_EXERCISE_IDS
        }

    assert first_ids == second_ids
    assert len(set(second_ids.values())) == 24


async def test_adaptive_seed_rerun_restores_mutable_content_in_place(uow_factory) -> None:
    await seed_curriculum()
    await seed_adaptive_profiles()

    target_exercise_id = next(iter(SEEDED_EXERCISE_IDS))
    expected_difficulty_score = _DIFFICULTY_SCORES[DifficultyLevel.BEGINNER]

    async with uow_factory() as uow:
        original_profile = await uow.adaptive_profiles.get_by_exercise(target_exercise_id)
        assert original_profile is not None
        mutated_profile = original_profile.model_copy(
            update={"base_difficulty_score": 0.99}
        )
        await uow.adaptive_profiles.upsert(mutated_profile)
        await uow.commit()

    async with uow_factory() as uow:
        drifted_profile = await uow.adaptive_profiles.get_by_exercise(target_exercise_id)
        assert drifted_profile is not None
        assert drifted_profile.base_difficulty_score == pytest.approx(0.99)

    await seed_adaptive_profiles()

    async with uow_factory() as uow:
        restored_profile = await uow.adaptive_profiles.get_by_exercise(target_exercise_id)
        assert restored_profile is not None
        assert restored_profile.profile_id == original_profile.profile_id
        assert restored_profile.base_difficulty_score == pytest.approx(expected_difficulty_score)


async def test_curriculum_then_adaptive_rerun_in_order_is_idempotent(uow_factory) -> None:
    await seed_curriculum()
    await seed_adaptive_profiles()
    await seed_curriculum()
    await seed_adaptive_profiles()

    diagnostic_count = 0
    review_count = 0
    remediation_count = 0
    async with uow_factory() as uow:
        profile_ids = set()
        for exercise_id in SEEDED_EXERCISE_IDS:
            profile = await uow.adaptive_profiles.get_by_exercise(exercise_id)
            assert profile is not None
            assert profile.profile_id == _profile_id(exercise_id)
            profile_ids.add(profile.profile_id)
            if profile.diagnostic_eligible:
                diagnostic_count += 1
            if profile.review_eligible:
                review_count += 1
            if profile.remediation_eligible:
                remediation_count += 1

    assert len(profile_ids) == 24
    assert diagnostic_count == 8
    assert review_count == 16
    assert remediation_count == 8
