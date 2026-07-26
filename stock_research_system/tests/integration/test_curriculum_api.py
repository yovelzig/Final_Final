"""Integration tests for `/api/v1/learning-paths`, `/modules`, `/lessons`,
`/exercises`, and attempt/answer endpoints against the real PostgreSQL
test database, driven over HTTP.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text

from tests.integration.conftest import auth_headers, promote_role, register_account
from stock_research_core.domain.learning.enums import DifficultyLevel, ExerciseType, FinancialSkillCategory, LessonStatus
from stock_research_core.domain.learning.models import Exercise, ExerciseOption, Lesson, LearningModule, LearningPath, Skill
from stock_research_core.infrastructure.database.repositories.attempt_repository import (
    SqlAlchemyAttemptRepository,
)


class _TwoPartyBarrier:
    """A deterministic rendezvous point for exactly two coroutines.

    Both callers must arrive at `wait()` before either is released, so a
    test using this to gate a repository call proves genuine concurrent
    arrival at that call - not merely that `asyncio.gather` was used.
    """

    def __init__(self) -> None:
        self.count = 0
        self.event = asyncio.Event()

    async def wait(self) -> None:
        self.count += 1
        if self.count >= 2:
            self.event.set()
        await self.event.wait()

pytestmark = pytest.mark.integration


def _email() -> str:
    return f"curric-{uuid.uuid4().hex[:10]}@example.com"


async def _seed_lesson_with_exercise(uow_factory) -> dict:
    async with uow_factory() as uow:
        skill = await uow.curriculum.upsert_skill(
            Skill(
                code=f"SKILL_{uuid.uuid4().hex[:8].upper()}", name="Skill", description="d",
                category=FinancialSkillCategory.MONEY_BASICS, difficulty=DifficultyLevel.BEGINNER,
            )
        )
        path = await uow.curriculum.upsert_path(
            LearningPath(
                code=f"path-{uuid.uuid4().hex[:8]}", title="Path", description="d",
                difficulty=DifficultyLevel.BEGINNER, position=0, estimated_minutes=10, published=True,
            )
        )
        module = await uow.curriculum.upsert_module(
            LearningModule(
                path_id=path.path_id, code="mod", title="Module", description="d", position=0,
                estimated_minutes=10, published=True,
            )
        )
        lesson = await uow.curriculum.upsert_lesson(
            Lesson(
                module_id=module.module_id, code="lesson", title="Lesson", summary="s",
                content_markdown="# c", difficulty=DifficultyLevel.BEGINNER, status=LessonStatus.PUBLISHED,
                position=0, estimated_minutes=10, primary_skill_id=skill.skill_id,
            )
        )
        exercise = await uow.curriculum.upsert_exercise(
            Exercise(
                lesson_id=lesson.lesson_id, exercise_type=ExerciseType.SINGLE_CHOICE, prompt="P?",
                explanation="E.", difficulty=DifficultyLevel.BEGINNER, position=0, skill_ids=[skill.skill_id],
                maximum_score=1.0, passing_score=1.0,
            )
        )
        correct = ExerciseOption(exercise_id=exercise.exercise_id, option_key="a", content="Right", position=0, is_correct=True)
        incorrect = ExerciseOption(exercise_id=exercise.exercise_id, option_key="b", content="Wrong", position=1, is_correct=False)
        await uow.curriculum.upsert_options([correct, incorrect])
        await uow.commit()
    return {
        "path_id": path.path_id, "module_id": module.module_id, "lesson_id": lesson.lesson_id,
        "exercise_id": exercise.exercise_id, "correct_option_id": correct.option_id,
    }


async def test_full_catalog_and_attempt_flow(api_client, uow_factory) -> None:
    world = await _seed_lesson_with_exercise(uow_factory)
    headers = await auth_headers(api_client, email=_email())

    r = await api_client.get("/api/v1/learning-paths", headers=headers)
    assert r.status_code == 200
    assert any(p["path_id"] == str(world["path_id"]) for p in r.json())

    r = await api_client.get(f"/api/v1/learning-paths/{world['path_id']}", headers=headers)
    assert r.status_code == 200

    r = await api_client.get(f"/api/v1/learning-paths/{world['path_id']}/modules", headers=headers)
    assert r.status_code == 200
    assert any(m["module_id"] == str(world["module_id"]) for m in r.json())

    r = await api_client.get(f"/api/v1/modules/{world['module_id']}/lessons", headers=headers)
    assert r.status_code == 200
    assert any(lesson["lesson_id"] == str(world["lesson_id"]) for lesson in r.json())

    r = await api_client.get(f"/api/v1/lessons/{world['lesson_id']}/exercises", headers=headers)
    assert r.status_code == 200
    exercises = r.json()
    assert len(exercises) == 1
    exercise = exercises[0]
    assert "is_correct" not in exercise
    assert "explanation" not in exercise
    assert "configuration" not in exercise
    for option in exercise["options"]:
        assert "is_correct" not in option
        assert "feedback" not in option

    r = await api_client.get(f"/api/v1/exercises/{world['exercise_id']}", headers=headers)
    assert r.status_code == 200
    single_exercise = r.json()
    assert single_exercise["exercise_id"] == str(world["exercise_id"])
    assert "is_correct" not in single_exercise
    assert "explanation" not in single_exercise
    assert "configuration" not in single_exercise
    for option in single_exercise["options"]:
        assert "is_correct" not in option
        assert "feedback" not in option

    r = await api_client.get(f"/api/v1/exercises/{uuid.uuid4()}", headers=headers)
    assert r.status_code == 404

    r = await api_client.post(f"/api/v1/exercises/{world['exercise_id']}/attempts", headers=headers, json={})
    assert r.status_code in (200, 201)
    attempt_id = r.json()["attempt_id"]

    r = await api_client.get(f"/api/v1/attempts/{attempt_id}", headers=headers)
    assert r.status_code == 200

    r = await api_client.post(
        f"/api/v1/attempts/{attempt_id}/answers", headers=headers,
        json={"selected_option_ids": [str(world["correct_option_id"])]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["attempt"]["is_correct"] is True
    assert body["explanation"] == "E."


async def test_ungraded_exercise_returns_null_explanation(api_client, uow_factory) -> None:
    world = await _seed_lesson_with_exercise(uow_factory)
    async with uow_factory() as uow:
        original_exercise = await uow.curriculum.get_exercise(world["exercise_id"])
        assert original_exercise is not None
        text_exercise = await uow.curriculum.upsert_exercise(
            Exercise(
                lesson_id=world["lesson_id"], exercise_type=ExerciseType.TEXT_RESPONSE, prompt="Explain.",
                explanation="No single correct wording.", difficulty=DifficultyLevel.BEGINNER, position=1,
                skill_ids=original_exercise.skill_ids, maximum_score=1.0, passing_score=1.0,
            )
        )
        await uow.commit()
    headers = await auth_headers(api_client, email=_email())

    r = await api_client.post(f"/api/v1/exercises/{text_exercise.exercise_id}/attempts", headers=headers, json={})
    attempt_id = r.json()["attempt_id"]

    r = await api_client.post(
        f"/api/v1/attempts/{attempt_id}/answers", headers=headers,
        json={"text_answer": "My own explanation."},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["attempt"]["is_correct"] is None
    assert body["explanation"] is None


async def test_resubmitting_a_graded_attempt_returns_conflict(api_client, uow_factory) -> None:
    world = await _seed_lesson_with_exercise(uow_factory)
    headers = await auth_headers(api_client, email=_email())

    r = await api_client.post(f"/api/v1/exercises/{world['exercise_id']}/attempts", headers=headers, json={})
    attempt_id = r.json()["attempt_id"]

    payload = {"selected_option_ids": [str(world["correct_option_id"])]}
    first = await api_client.post(f"/api/v1/attempts/{attempt_id}/answers", headers=headers, json=payload)
    assert first.status_code == 200

    second = await api_client.post(f"/api/v1/attempts/{attempt_id}/answers", headers=headers, json=payload)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "INVALID_ATTEMPT_STATE"

    mastery = await api_client.get("/api/v1/learners/me/mastery", headers=headers)
    assert any(m["total_attempts"] == 1 for m in mastery.json()["items"])


async def test_concurrent_duplicate_submission_is_serialized(api_client, uow_factory, monkeypatch) -> None:
    world = await _seed_lesson_with_exercise(uow_factory)
    headers = await auth_headers(api_client, email=_email())

    r = await api_client.post(f"/api/v1/exercises/{world['exercise_id']}/attempts", headers=headers, json={})
    attempt_id = r.json()["attempt_id"]
    payload = {"selected_option_ids": [str(world["correct_option_id"])]}

    # Two genuinely separate HTTP requests over the same ASGI app: FastAPI's
    # dependency injection gives each one its own `SqlAlchemyUnitOfWork` (its
    # own session/connection from the pool). `asyncio.gather` alone proves
    # they're issued concurrently, but not that both actually reached the
    # locking call at the same time - one could simply finish before the
    # other starts. The barrier below forces both requests' underlying
    # `get_attempt_for_update` calls to rendezvous immediately before either
    # executes the real `SELECT ... FOR UPDATE`, so the resulting 200/409
    # split is proven to come from genuine contention on the row lock, not
    # from request-scheduling luck.
    barrier = _TwoPartyBarrier()
    session_ids: list[int] = []
    original_get_attempt_for_update = SqlAlchemyAttemptRepository.get_attempt_for_update

    async def instrumented_get_attempt_for_update(self, attempt_id_arg):
        session_ids.append(id(self._session))
        await barrier.wait()
        return await original_get_attempt_for_update(self, attempt_id_arg)

    monkeypatch.setattr(
        SqlAlchemyAttemptRepository, "get_attempt_for_update", instrumented_get_attempt_for_update
    )

    async def submit_once():
        return await api_client.post(
            f"/api/v1/attempts/{attempt_id}/answers", headers=headers, json=payload
        )

    responses = await asyncio.wait_for(
        asyncio.gather(submit_once(), submit_once()), timeout=10
    )

    assert barrier.count == 2
    assert len(session_ids) == 2
    assert session_ids[0] != session_ids[1], "both requests must use distinct database sessions"

    status_codes = sorted(r.status_code for r in responses)
    assert status_codes == [200, 409]
    conflict_response = next(r for r in responses if r.status_code == 409)
    assert conflict_response.json()["error"]["code"] == "INVALID_ATTEMPT_STATE"

    async with uow_factory() as uow:
        answer_count = (
            await uow._session.execute(  # noqa: SLF001 - test-only direct read for row-count proof
                text("SELECT COUNT(*) FROM exercise_answers WHERE attempt_id = :attempt_id"),
                {"attempt_id": uuid.UUID(attempt_id)},
            )
        ).scalar_one()
    assert answer_count == 1

    mastery = await api_client.get("/api/v1/learners/me/mastery", headers=headers)
    assert any(m["total_attempts"] == 1 for m in mastery.json()["items"])

    progress = await api_client.get("/api/v1/learners/me/progress", headers=headers)
    lesson_progress = [
        p for p in progress.json()["items"] if p["lesson_id"] == str(world["lesson_id"])
    ]
    assert len(lesson_progress) == 1
    assert lesson_progress[0]["attempt_count"] == 1


async def test_nonexistent_learning_path_returns_404(api_client) -> None:
    headers = await auth_headers(api_client, email=_email())
    response = await api_client.get(f"/api/v1/learning-paths/{uuid.uuid4()}", headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_attempt_ownership_is_enforced(api_client, uow_factory) -> None:
    world = await _seed_lesson_with_exercise(uow_factory)
    owner_headers = await auth_headers(api_client, email=_email())
    other_headers = await auth_headers(api_client, email=_email())

    r = await api_client.post(
        f"/api/v1/exercises/{world['exercise_id']}/attempts", headers=owner_headers, json={}
    )
    attempt_id = r.json()["attempt_id"]

    r = await api_client.get(f"/api/v1/attempts/{attempt_id}", headers=other_headers)
    assert r.status_code == 404

    r = await api_client.post(
        f"/api/v1/attempts/{attempt_id}/answers", headers=other_headers,
        json={"selected_option_ids": [str(world["correct_option_id"])]},
    )
    assert r.status_code == 404


async def test_catalog_requires_authentication(api_client) -> None:
    response = await api_client.get("/api/v1/learning-paths")
    assert response.status_code == 401


async def _seed_hierarchy_variant(
    uow_factory,
    *,
    path_published: bool = True,
    module_published: bool = True,
    lesson_status: LessonStatus = LessonStatus.PUBLISHED,
    exercise_active: bool = True,
) -> dict:
    async with uow_factory() as uow:
        skill = await uow.curriculum.upsert_skill(
            Skill(
                code=f"SKILL_{uuid.uuid4().hex[:8].upper()}", name="Skill", description="d",
                category=FinancialSkillCategory.MONEY_BASICS, difficulty=DifficultyLevel.BEGINNER,
            )
        )
        path = await uow.curriculum.upsert_path(
            LearningPath(
                code=f"path-{uuid.uuid4().hex[:8]}", title="Path", description="d",
                difficulty=DifficultyLevel.BEGINNER, position=0, estimated_minutes=10,
                published=path_published,
            )
        )
        module = await uow.curriculum.upsert_module(
            LearningModule(
                path_id=path.path_id, code="mod", title="Module", description="d", position=0,
                estimated_minutes=10, published=module_published,
            )
        )
        lesson = await uow.curriculum.upsert_lesson(
            Lesson(
                module_id=module.module_id, code="lesson", title="Lesson", summary="s",
                content_markdown="# c", difficulty=DifficultyLevel.BEGINNER, status=lesson_status,
                position=0, estimated_minutes=10, primary_skill_id=skill.skill_id,
            )
        )
        exercise = await uow.curriculum.upsert_exercise(
            Exercise(
                lesson_id=lesson.lesson_id, exercise_type=ExerciseType.SINGLE_CHOICE, prompt="P?",
                explanation="E.", difficulty=DifficultyLevel.BEGINNER, position=0, skill_ids=[skill.skill_id],
                maximum_score=1.0, passing_score=1.0, active=exercise_active,
            )
        )
        await uow.commit()
    return {
        "path_id": path.path_id, "module_id": module.module_id, "lesson_id": lesson.lesson_id,
        "exercise_id": exercise.exercise_id,
    }


async def test_unpublished_path_hides_the_path_and_every_descendant(api_client, uow_factory) -> None:
    world = await _seed_hierarchy_variant(uow_factory, path_published=False)
    headers = await auth_headers(api_client, email=_email())

    assert (await api_client.get(f"/api/v1/learning-paths/{world['path_id']}", headers=headers)).status_code == 404
    paths = await api_client.get("/api/v1/learning-paths", headers=headers)
    assert str(world["path_id"]) not in {p["path_id"] for p in paths.json()}
    assert (
        await api_client.get(f"/api/v1/learning-paths/{world['path_id']}/modules", headers=headers)
    ).status_code == 404
    assert (await api_client.get(f"/api/v1/modules/{world['module_id']}", headers=headers)).status_code == 404
    assert (
        await api_client.get(f"/api/v1/modules/{world['module_id']}/lessons", headers=headers)
    ).status_code == 404
    assert (await api_client.get(f"/api/v1/lessons/{world['lesson_id']}", headers=headers)).status_code == 404
    assert (
        await api_client.get(f"/api/v1/lessons/{world['lesson_id']}/exercises", headers=headers)
    ).status_code == 404
    assert (await api_client.get(f"/api/v1/exercises/{world['exercise_id']}", headers=headers)).status_code == 404


async def test_unpublished_module_is_excluded_and_hidden_directly(api_client, uow_factory) -> None:
    world = await _seed_hierarchy_variant(uow_factory, module_published=False)
    headers = await auth_headers(api_client, email=_email())

    modules = await api_client.get(f"/api/v1/learning-paths/{world['path_id']}/modules", headers=headers)
    assert modules.status_code == 200
    assert str(world["module_id"]) not in {m["module_id"] for m in modules.json()}
    assert (await api_client.get(f"/api/v1/modules/{world['module_id']}", headers=headers)).status_code == 404
    assert (await api_client.get(f"/api/v1/lessons/{world['lesson_id']}", headers=headers)).status_code == 404
    assert (await api_client.get(f"/api/v1/exercises/{world['exercise_id']}", headers=headers)).status_code == 404


async def test_published_module_under_unpublished_path_is_hidden(api_client, uow_factory) -> None:
    world = await _seed_hierarchy_variant(uow_factory, path_published=False, module_published=True)
    headers = await auth_headers(api_client, email=_email())

    assert (
        await api_client.get(f"/api/v1/learning-paths/{world['path_id']}/modules", headers=headers)
    ).status_code == 404
    assert (await api_client.get(f"/api/v1/modules/{world['module_id']}", headers=headers)).status_code == 404


async def test_unpublished_lesson_is_excluded_and_hidden_directly(api_client, uow_factory) -> None:
    world = await _seed_hierarchy_variant(uow_factory, lesson_status=LessonStatus.DRAFT)
    headers = await auth_headers(api_client, email=_email())

    lessons = await api_client.get(f"/api/v1/modules/{world['module_id']}/lessons", headers=headers)
    assert lessons.status_code == 200
    assert str(world["lesson_id"]) not in {lesson["lesson_id"] for lesson in lessons.json()}
    assert (await api_client.get(f"/api/v1/lessons/{world['lesson_id']}", headers=headers)).status_code == 404
    assert (
        await api_client.get(f"/api/v1/lessons/{world['lesson_id']}/exercises", headers=headers)
    ).status_code == 404
    assert (await api_client.get(f"/api/v1/exercises/{world['exercise_id']}", headers=headers)).status_code == 404


async def test_published_lesson_under_unpublished_module_is_hidden(api_client, uow_factory) -> None:
    world = await _seed_hierarchy_variant(
        uow_factory, module_published=False, lesson_status=LessonStatus.PUBLISHED
    )
    headers = await auth_headers(api_client, email=_email())

    assert (
        await api_client.get(f"/api/v1/modules/{world['module_id']}/lessons", headers=headers)
    ).status_code == 404
    assert (await api_client.get(f"/api/v1/lessons/{world['lesson_id']}", headers=headers)).status_code == 404


async def test_inactive_exercise_is_excluded_and_hidden_directly(api_client, uow_factory) -> None:
    world = await _seed_hierarchy_variant(uow_factory, exercise_active=False)
    headers = await auth_headers(api_client, email=_email())

    exercises = await api_client.get(f"/api/v1/lessons/{world['lesson_id']}/exercises", headers=headers)
    assert exercises.status_code == 200
    assert exercises.json() == []
    assert (await api_client.get(f"/api/v1/exercises/{world['exercise_id']}", headers=headers)).status_code == 404


async def test_active_exercise_under_hidden_lesson_is_hidden(api_client, uow_factory) -> None:
    world = await _seed_hierarchy_variant(uow_factory, lesson_status=LessonStatus.DRAFT, exercise_active=True)
    headers = await auth_headers(api_client, email=_email())

    assert (
        await api_client.get(f"/api/v1/lessons/{world['lesson_id']}/exercises", headers=headers)
    ).status_code == 404
    assert (await api_client.get(f"/api/v1/exercises/{world['exercise_id']}", headers=headers)).status_code == 404


async def _register_learner(api_client) -> tuple[dict, dict]:
    """Registers a fresh learner and returns (headers, learner_id-bearing body)."""
    body = await register_account(api_client, email=_email())
    headers = {"Authorization": f"Bearer {body['tokens']['access_token']}"}
    return headers, body


async def _assert_no_attempts_created(uow_factory, *, learner_id: uuid.UUID, exercise_id: uuid.UUID) -> None:
    async with uow_factory() as uow:
        attempts = await uow.attempts.list_attempts(learner_id, exercise_id)
    assert attempts == []


async def test_starting_an_attempt_on_an_inactive_exercise_returns_404(api_client, uow_factory) -> None:
    world = await _seed_hierarchy_variant(uow_factory, exercise_active=False)
    headers, body = await _register_learner(api_client)
    learner_id = uuid.UUID(body["learner"]["learner_id"])

    r = await api_client.post(f"/api/v1/exercises/{world['exercise_id']}/attempts", headers=headers, json={})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
    await _assert_no_attempts_created(uow_factory, learner_id=learner_id, exercise_id=world["exercise_id"])


async def test_starting_an_attempt_under_an_unpublished_lesson_returns_404(api_client, uow_factory) -> None:
    world = await _seed_hierarchy_variant(uow_factory, lesson_status=LessonStatus.DRAFT)
    headers, body = await _register_learner(api_client)
    learner_id = uuid.UUID(body["learner"]["learner_id"])

    r = await api_client.post(f"/api/v1/exercises/{world['exercise_id']}/attempts", headers=headers, json={})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
    await _assert_no_attempts_created(uow_factory, learner_id=learner_id, exercise_id=world["exercise_id"])


async def test_starting_an_attempt_under_an_unpublished_module_returns_404(api_client, uow_factory) -> None:
    world = await _seed_hierarchy_variant(uow_factory, module_published=False)
    headers, body = await _register_learner(api_client)
    learner_id = uuid.UUID(body["learner"]["learner_id"])

    r = await api_client.post(f"/api/v1/exercises/{world['exercise_id']}/attempts", headers=headers, json={})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
    await _assert_no_attempts_created(uow_factory, learner_id=learner_id, exercise_id=world["exercise_id"])


async def test_starting_an_attempt_under_an_unpublished_path_returns_404(api_client, uow_factory) -> None:
    world = await _seed_hierarchy_variant(uow_factory, path_published=False)
    headers, body = await _register_learner(api_client)
    learner_id = uuid.UUID(body["learner"]["learner_id"])

    r = await api_client.post(f"/api/v1/exercises/{world['exercise_id']}/attempts", headers=headers, json={})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
    await _assert_no_attempts_created(uow_factory, learner_id=learner_id, exercise_id=world["exercise_id"])


async def test_starting_an_attempt_on_a_fully_visible_exercise_still_succeeds(api_client, uow_factory) -> None:
    world = await _seed_hierarchy_variant(uow_factory)
    headers, body = await _register_learner(api_client)
    learner_id = uuid.UUID(body["learner"]["learner_id"])

    r = await api_client.post(f"/api/v1/exercises/{world['exercise_id']}/attempts", headers=headers, json={})
    assert r.status_code in (200, 201)
    async with uow_factory() as uow:
        attempts = await uow.attempts.list_attempts(learner_id, world["exercise_id"])
    assert len(attempts) == 1


async def test_inactive_exercise_is_hidden_and_does_not_block_completion(api_client, uow_factory) -> None:
    world = await _seed_lesson_with_exercise(uow_factory)
    async with uow_factory() as uow:
        original_exercise = await uow.curriculum.get_exercise(world["exercise_id"])
        assert original_exercise is not None
        inactive_exercise = await uow.curriculum.upsert_exercise(
            Exercise(
                lesson_id=world["lesson_id"], exercise_type=ExerciseType.SINGLE_CHOICE, prompt="Inactive?",
                explanation="Inactive.", difficulty=DifficultyLevel.BEGINNER, position=1,
                skill_ids=original_exercise.skill_ids, maximum_score=1.0, passing_score=1.0, active=False,
            )
        )
        await uow.commit()
    headers, _body = await _register_learner(api_client)

    exercises = await api_client.get(f"/api/v1/lessons/{world['lesson_id']}/exercises", headers=headers)
    assert exercises.status_code == 200
    exercise_ids = {ex["exercise_id"] for ex in exercises.json()}
    assert exercise_ids == {str(world["exercise_id"])}
    assert str(inactive_exercise.exercise_id) not in exercise_ids

    r = await api_client.post(f"/api/v1/exercises/{world['exercise_id']}/attempts", headers=headers, json={})
    assert r.status_code in (200, 201)
    attempt_id = r.json()["attempt_id"]

    r = await api_client.post(
        f"/api/v1/attempts/{attempt_id}/answers", headers=headers,
        json={"selected_option_ids": [str(world["correct_option_id"])]},
    )
    assert r.status_code == 200
    submit_body = r.json()
    assert submit_body["updated_progress"]["status"] == "COMPLETED"
    assert submit_body["updated_progress"]["completion_percentage"] == 100

    progress = await api_client.get("/api/v1/learners/me/progress", headers=headers)
    lesson_progress = [
        p for p in progress.json()["items"] if p["lesson_id"] == str(world["lesson_id"])
    ]
    assert len(lesson_progress) == 1
    assert lesson_progress[0]["status"] == "COMPLETED"
    assert lesson_progress[0]["completion_percentage"] == 100


async def test_admin_can_author_unpublished_content_while_learners_cannot_see_it(
    api_client, uow_factory
) -> None:
    email = _email()
    account = await register_account(api_client, email=email)
    await promote_role(uow_factory, account_id=account["account"]["account_id"], role="CONTENT_EDITOR")
    # The original token's role claim no longer matches the account after
    # `promote_role`'s direct DB write - log in again for a fresh token
    # carrying CONTENT_EDITOR (same pattern as `tests/integration/test_admin_api.py`).
    login = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": "StrongPassword123!"}
    )
    assert login.status_code == 200, login.text
    admin_headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}

    r = await api_client.put(
        "/api/v1/admin/curriculum/paths", headers=admin_headers,
        json={
            "code": f"admin-draft-path-{uuid.uuid4().hex[:8]}", "title": "Draft Path", "description": "d",
            "difficulty": "BEGINNER", "position": 0, "estimated_minutes": 10, "published": False,
        },
    )
    assert r.status_code == 200, r.text
    draft_path = r.json()
    assert draft_path["published"] is False

    r = await api_client.put(
        f"/api/v1/admin/curriculum/paths/{draft_path['path_id']}/modules", headers=admin_headers,
        json={"code": "draft-mod", "title": "Draft Module", "description": "d", "position": 0,
              "estimated_minutes": 10, "published": False},
    )
    assert r.status_code == 200, r.text
    draft_module = r.json()
    assert draft_module["published"] is False

    learner_headers = await auth_headers(api_client, email=_email())
    assert (
        await api_client.get(f"/api/v1/learning-paths/{draft_path['path_id']}", headers=learner_headers)
    ).status_code == 404
