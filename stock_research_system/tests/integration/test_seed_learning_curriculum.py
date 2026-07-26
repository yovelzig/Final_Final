"""PostgreSQL integration tests: scripts/seed_learning_curriculum.py.

Verifies the deterministic seeded "Investing Foundations" subtree only -
never asserts that shared tables (e.g. `financial_skills`) contain
nothing else. The expected hierarchy below is an independent, hard-coded
oracle (not derived from the production script's own `MODULES`/`SKILLS`
constants), so an accidental change to the seed data and the test oracle
can never silently move together.
"""

from __future__ import annotations

import pytest

from scripts.seed_learning_curriculum import _id, seed as seed_curriculum
from stock_research_core.domain.learning.enums import LessonStatus
from stock_research_core.infrastructure.database.config import DatabaseSettings

pytestmark = pytest.mark.integration

EXPECTED_SKILL_CODES = [
    "MONEY_BASICS",
    "INFLATION",
    "COMPOUND_INTEREST",
    "STOCKS",
    "BONDS",
    "FUNDS_AND_ETFS",
    "RISK_AND_RETURN",
    "DIVERSIFICATION",
]

EXPECTED_MODULES = [
    ("money-and-inflation", 0),
    ("stocks-bonds-and-funds", 1),
    ("risk-and-return", 2),
    ("diversification", 3),
]

EXPECTED_LESSONS_BY_MODULE = {
    "money-and-inflation": [
        ("what-money-is-for", 0, "MONEY_BASICS"),
        ("what-inflation-does", 1, "INFLATION"),
    ],
    "stocks-bonds-and-funds": [
        ("what-a-stock-represents", 0, "STOCKS"),
        ("how-bonds-and-funds-work", 1, "BONDS"),
    ],
    "risk-and-return": [
        ("understanding-risk-and-return", 0, "RISK_AND_RETURN"),
        ("simple-vs-compound-interest", 1, "COMPOUND_INTEREST"),
    ],
    "diversification": [
        ("why-diversification-matters", 0, "DIVERSIFICATION"),
        ("concentration-risk", 1, "DIVERSIFICATION"),
    ],
}

EXPECTED_EXERCISE_KEYS_BY_LESSON = {
    "what-money-is-for": [
        "money-functions-single-choice",
        "money-store-of-value-true-false",
        "money-functions-multiple-choice",
    ],
    "what-inflation-does": [
        "inflation-definition-single-choice",
        "inflation-rule-of-72-numeric",
        "inflation-purchasing-power-true-false",
    ],
    "what-a-stock-represents": [
        "stock-ownership-single-choice",
        "stock-benefit-true-false",
        "stock-price-factors-multiple-choice",
    ],
    "how-bonds-and-funds-work": [
        "bond-definition-single-choice",
        "etf-definition-single-choice",
        "fund-exposure-true-false",
    ],
    "understanding-risk-and-return": [
        "risk-return-relationship-single-choice",
        "diversification-guarantee-true-false",
        "return-percentage-numeric",
    ],
    "simple-vs-compound-interest": [
        "simple-vs-compound-single-choice",
        "simple-interest-numeric",
        "compound-growth-ordering",
    ],
    "why-diversification-matters": [
        "most-diversified-portfolio-single-choice",
        "diversification-guarantee-true-false-2",
        "diversification-examples-multiple-choice",
    ],
    "concentration-risk": [
        "concentration-risk-definition-single-choice",
        "concentration-vs-spread-true-false",
        "equal-split-percentage-numeric",
    ],
}


@pytest.fixture(autouse=True)
def _seed_scripts_use_test_database(
    monkeypatch: pytest.MonkeyPatch,
    database_settings: DatabaseSettings,
) -> None:
    assert database_settings.test_database_url is not None
    monkeypatch.setenv("DATABASE_URL", database_settings.test_database_url)


async def _collect_deterministic_ids(uow_factory) -> dict:
    """Snapshot every deterministic ID/relationship in the seeded subtree."""
    async with uow_factory() as uow:
        path = await uow.curriculum.get_path(_id("path:investing-foundations"))
        assert path is not None
        modules = await uow.curriculum.list_modules(path.path_id)
        module_ids = {module.code: module.module_id for module in modules}
        lesson_ids: dict[str, object] = {}
        exercise_ids: dict[str, object] = {}
        module_parent = {}
        lesson_parent = {}
        exercise_parent = {}
        for module in modules:
            module_parent[module.code] = module.path_id
            lessons = await uow.curriculum.list_lessons(module.module_id)
            for lesson in lessons:
                lesson_ids[lesson.code] = lesson.lesson_id
                lesson_parent[lesson.code] = lesson.module_id
                exercises = await uow.curriculum.list_exercises(lesson.lesson_id)
                for exercise in exercises:
                    matching_key = next(
                        key
                        for key in EXPECTED_EXERCISE_KEYS_BY_LESSON[lesson.code]
                        if _id(f"exercise:{key}") == exercise.exercise_id
                    )
                    exercise_ids[matching_key] = exercise.exercise_id
                    exercise_parent[matching_key] = exercise.lesson_id
        return {
            "path_id": path.path_id,
            "module_ids": module_ids,
            "lesson_ids": lesson_ids,
            "exercise_ids": exercise_ids,
            "module_parent": module_parent,
            "lesson_parent": lesson_parent,
            "exercise_parent": exercise_parent,
        }


async def test_seed_curriculum_creates_exact_deterministic_hierarchy(uow_factory) -> None:
    await seed_curriculum()

    async with uow_factory() as uow:
        path = await uow.curriculum.get_path(_id("path:investing-foundations"))
        assert path is not None
        assert path.code == "investing-foundations"
        assert path.published is True
        assert path.position == 0

        modules = await uow.curriculum.list_modules(path.path_id)
        assert [(module.code, module.position) for module in modules] == EXPECTED_MODULES

        for module in modules:
            assert module.module_id == _id(f"module:{module.code}")
            assert module.path_id == path.path_id
            assert module.published is True

            expected_lessons = EXPECTED_LESSONS_BY_MODULE[module.code]
            lessons = await uow.curriculum.list_lessons(module.module_id)
            assert [(lesson.code, lesson.position) for lesson in lessons] == [
                (code, position) for code, position, _ in expected_lessons
            ]

            for lesson in lessons:
                expected_primary_code = next(
                    primary_code
                    for code, _, primary_code in expected_lessons
                    if code == lesson.code
                )
                assert lesson.lesson_id == _id(f"lesson:{lesson.code}")
                assert lesson.status == LessonStatus.PUBLISHED
                assert lesson.primary_skill_id == _id(f"skill:{expected_primary_code}")
                assert lesson.module_id == module.module_id

                expected_keys = EXPECTED_EXERCISE_KEYS_BY_LESSON[lesson.code]
                expected_exercise_ids = {_id(f"exercise:{key}") for key in expected_keys}
                exercises = await uow.curriculum.list_exercises(lesson.lesson_id)
                assert len(exercises) == 3
                assert {exercise.position for exercise in exercises} == {0, 1, 2}
                assert {exercise.exercise_id for exercise in exercises} == expected_exercise_ids
                for exercise in exercises:
                    assert exercise.active is True
                    assert exercise.lesson_id == lesson.lesson_id

        for code in EXPECTED_SKILL_CODES:
            skill = await uow.curriculum.get_skill(_id(f"skill:{code}"))
            assert skill is not None
            assert skill.skill_id == _id(f"skill:{code}")
            assert skill.code == code


async def test_seed_curriculum_rerun_is_idempotent_and_preserves_ids(uow_factory) -> None:
    await seed_curriculum()
    first = await _collect_deterministic_ids(uow_factory)

    await seed_curriculum()
    second = await _collect_deterministic_ids(uow_factory)

    assert first == second
    assert len(second["module_ids"]) == 4
    assert len(second["lesson_ids"]) == 8
    assert len(second["exercise_ids"]) == 24


async def test_seed_curriculum_rerun_restores_mutable_content_in_place(uow_factory) -> None:
    await seed_curriculum()

    async with uow_factory() as uow:
        original_path = await uow.curriculum.get_path(_id("path:investing-foundations"))
        assert original_path is not None
        mutated_path = original_path.model_copy(update={"description": "SENTINEL-DRIFTED-DESCRIPTION"})
        await uow.curriculum.upsert_path(mutated_path)
        await uow.commit()

    async with uow_factory() as uow:
        drifted_path = await uow.curriculum.get_path(_id("path:investing-foundations"))
        assert drifted_path is not None
        assert drifted_path.description == "SENTINEL-DRIFTED-DESCRIPTION"

    await seed_curriculum()

    async with uow_factory() as uow:
        restored_path = await uow.curriculum.get_path(_id("path:investing-foundations"))
        assert restored_path is not None
        assert restored_path.path_id == original_path.path_id
        assert restored_path.description == original_path.description
        assert restored_path.description != "SENTINEL-DRIFTED-DESCRIPTION"


async def test_seed_curriculum_has_no_duplicate_seed_natural_keys(uow_factory) -> None:
    await seed_curriculum()
    await seed_curriculum()

    async with uow_factory() as uow:
        paths = await uow.curriculum.list_paths(published_only=False)
        matching_paths = [path for path in paths if path.code == "investing-foundations"]
        assert len(matching_paths) == 1
        path = matching_paths[0]

        modules = await uow.curriculum.list_modules(path.path_id)
        module_keys = [(module.path_id, module.code) for module in modules]
        assert len(module_keys) == len(set(module_keys))

        for module in modules:
            lessons = await uow.curriculum.list_lessons(module.module_id)
            lesson_keys = [(lesson.module_id, lesson.code) for lesson in lessons]
            assert len(lesson_keys) == len(set(lesson_keys))

            for lesson in lessons:
                exercises = await uow.curriculum.list_exercises(lesson.lesson_id)
                assert len(exercises) == 3
                assert {exercise.position for exercise in exercises} == {0, 1, 2}
                assert len({exercise.exercise_id for exercise in exercises}) == 3

                for exercise in exercises:
                    options = await uow.curriculum.list_options(exercise.exercise_id)
                    option_keys = [(option.exercise_id, option.option_key) for option in options]
                    assert len(option_keys) == len(set(option_keys))
