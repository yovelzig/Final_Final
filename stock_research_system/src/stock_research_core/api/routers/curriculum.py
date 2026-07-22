"""`/api/v1`: curriculum catalog (paths/modules/lessons/exercises,
learner-safe - never exposes correct-answer flags before submission)
and the learner's own exercise attempts/answers.

Catalog endpoints require only an authenticated account (any role);
attempt/answer endpoints are always scoped to the caller's own
`learner_id` and enforce ownership before returning or mutating an
existing attempt.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from stock_research_core.api.dependencies import get_uow_factory, require_learner, require_learner_identity
from stock_research_core.api.schemas.curriculum import (
    AttemptResponse,
    ExerciseResponse,
    LearningModuleResponse,
    LearningPathResponse,
    LessonResponse,
    StartAttemptRequest,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
)
from stock_research_core.api.schemas.learners import ProgressResponse, SkillMasteryResponse
from stock_research_core.application.exceptions import (
    ExerciseAttemptNotFoundError,
    ExerciseNotFoundError,
    LearningModuleNotFoundError,
    LearningPathNotFoundError,
    LessonNotFoundError,
)
from stock_research_core.application.learning.service import LearningService
from stock_research_core.domain.learning.models import ExerciseAnswer

router = APIRouter()


@router.get("/learning-paths", response_model=list[LearningPathResponse], dependencies=[Depends(require_learner)])
async def list_learning_paths(uow_factory: Annotated[object, Depends(get_uow_factory)]) -> list[LearningPathResponse]:
    async with uow_factory() as uow:
        paths = await uow.curriculum.list_paths(published_only=True)
    return [LearningPathResponse.from_domain(path) for path in paths]


@router.get(
    "/learning-paths/{path_id}", response_model=LearningPathResponse, dependencies=[Depends(require_learner)]
)
async def get_learning_path(
    path_id: UUID, uow_factory: Annotated[object, Depends(get_uow_factory)]
) -> LearningPathResponse:
    async with uow_factory() as uow:
        path = await uow.curriculum.get_path(path_id)
    if path is None:
        raise LearningPathNotFoundError(f"No learning path found with id '{path_id}'.")
    return LearningPathResponse.from_domain(path)


@router.get(
    "/learning-paths/{path_id}/modules", response_model=list[LearningModuleResponse],
    dependencies=[Depends(require_learner)],
)
async def list_modules(
    path_id: UUID, uow_factory: Annotated[object, Depends(get_uow_factory)]
) -> list[LearningModuleResponse]:
    async with uow_factory() as uow:
        modules = await uow.curriculum.list_modules(path_id)
    return [LearningModuleResponse.from_domain(module) for module in modules]


@router.get(
    "/modules/{module_id}", response_model=LearningModuleResponse, dependencies=[Depends(require_learner)]
)
async def get_module(
    module_id: UUID, uow_factory: Annotated[object, Depends(get_uow_factory)]
) -> LearningModuleResponse:
    async with uow_factory() as uow:
        module = await uow.curriculum.get_module(module_id)
    if module is None:
        raise LearningModuleNotFoundError(f"No learning module found with id '{module_id}'.")
    return LearningModuleResponse.from_domain(module)


@router.get(
    "/modules/{module_id}/lessons", response_model=list[LessonResponse], dependencies=[Depends(require_learner)]
)
async def list_lessons(
    module_id: UUID, uow_factory: Annotated[object, Depends(get_uow_factory)]
) -> list[LessonResponse]:
    async with uow_factory() as uow:
        lessons = await uow.curriculum.list_lessons(module_id)
    return [LessonResponse.from_domain(lesson) for lesson in lessons]


@router.get("/lessons/{lesson_id}", response_model=LessonResponse, dependencies=[Depends(require_learner)])
async def get_lesson(
    lesson_id: UUID, uow_factory: Annotated[object, Depends(get_uow_factory)]
) -> LessonResponse:
    async with uow_factory() as uow:
        lesson = await uow.curriculum.get_lesson(lesson_id)
    if lesson is None:
        raise LessonNotFoundError(f"No lesson found with id '{lesson_id}'.")
    return LessonResponse.from_domain(lesson)


@router.get(
    "/lessons/{lesson_id}/exercises", response_model=list[ExerciseResponse],
    dependencies=[Depends(require_learner)],
)
async def list_lesson_exercises(
    lesson_id: UUID, uow_factory: Annotated[object, Depends(get_uow_factory)]
) -> list[ExerciseResponse]:
    result = await LearningService(uow_factory).get_lesson_with_exercises(lesson_id)
    return [
        ExerciseResponse.from_domain(exercise, result.options_by_exercise.get(exercise.exercise_id, []))
        for exercise in result.exercises
    ]


@router.get(
    "/exercises/{exercise_id}", response_model=ExerciseResponse,
    dependencies=[Depends(require_learner)],
    summary="Get a single exercise by id (learner-safe)",
)
async def get_exercise(
    exercise_id: UUID, uow_factory: Annotated[object, Depends(get_uow_factory)]
) -> ExerciseResponse:
    async with uow_factory() as uow:
        exercise = await uow.curriculum.get_exercise(exercise_id)
        if exercise is None:
            raise ExerciseNotFoundError(f"No exercise found with id '{exercise_id}'.")
        options = await uow.curriculum.list_options(exercise_id)
    return ExerciseResponse.from_domain(exercise, options)


@router.post(
    "/exercises/{exercise_id}/attempts", response_model=AttemptResponse,
    summary="Start a new attempt at an exercise",
)
async def start_attempt(
    exercise_id: UUID,
    payload: StartAttemptRequest,
    learner_id: Annotated[UUID, Depends(require_learner_identity)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
) -> AttemptResponse:
    attempt = await LearningService(uow_factory).start_exercise_attempt(
        learner_id=learner_id, exercise_id=exercise_id, confidence_level=payload.confidence_level
    )
    return AttemptResponse.from_domain(attempt)


@router.get("/attempts/{attempt_id}", response_model=AttemptResponse, summary="Get one of my own attempts")
async def get_attempt(
    attempt_id: UUID,
    learner_id: Annotated[UUID, Depends(require_learner_identity)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
) -> AttemptResponse:
    async with uow_factory() as uow:
        attempt = await uow.attempts.get_attempt(attempt_id)
    if attempt is None or attempt.learner_id != learner_id:
        raise ExerciseAttemptNotFoundError(f"No exercise attempt found with id '{attempt_id}'.")
    return AttemptResponse.from_domain(attempt)


@router.post(
    "/attempts/{attempt_id}/answers", response_model=SubmitAnswerResponse,
    summary="Submit an answer for one of my own attempts",
    description="Grades the answer using the existing deterministic grading logic and updates skill "
    "mastery/progress accordingly. Never duplicates grading logic here.",
)
async def submit_answer(
    attempt_id: UUID,
    payload: SubmitAnswerRequest,
    learner_id: Annotated[UUID, Depends(require_learner_identity)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
) -> SubmitAnswerResponse:
    learning_service = LearningService(uow_factory)
    async with uow_factory() as uow:
        attempt = await uow.attempts.get_attempt(attempt_id)
    if attempt is None or attempt.learner_id != learner_id:
        raise ExerciseAttemptNotFoundError(f"No exercise attempt found with id '{attempt_id}'.")

    answer = ExerciseAnswer(
        attempt_id=attempt_id, selected_option_ids=payload.selected_option_ids,
        numeric_answer=payload.numeric_answer, text_answer=payload.text_answer,
        ordered_option_ids=payload.ordered_option_ids,
    )
    result = await learning_service.submit_answer(attempt_id=attempt_id, answer=answer)
    return SubmitAnswerResponse(
        attempt=AttemptResponse.from_domain(result.attempt),
        updated_mastery=[SkillMasteryResponse.from_domain(m) for m in result.updated_mastery],
        updated_progress=ProgressResponse.from_domain(result.updated_progress) if result.updated_progress else None,
    )
