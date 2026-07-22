"""Unit tests for `LessonTutorService`.

`GroundedAITutorService` is faked (its own behavior is covered by
`test_ai_tutor_service.py`) so these tests focus on
`LessonTutorService`'s own responsibilities: lesson/exercise existence
validation, target-skill derivation, and passing `exercise_submitted`
through accurately for the exercise-answer leakage guard.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from stock_research_core.application.ai_tutor.lesson_tutor import LessonTutorService
from stock_research_core.application.ai_tutor.models import TutorContext
from stock_research_core.application.exceptions import ExerciseNotFoundError, LessonNotFoundError
from stock_research_core.domain.ai_tutor.enums import TutorContextType, TutorConversationStatus
from stock_research_core.domain.ai_tutor.models import TutorConversation
from stock_research_core.domain.learning.enums import DifficultyLevel, ExerciseType, LessonStatus
from stock_research_core.domain.learning.models import Exercise, Lesson


class FakeCurriculumRepository:
    def __init__(self, lessons=None, exercises=None) -> None:
        self.lessons = {lesson.lesson_id: lesson for lesson in (lessons or [])}
        self.exercises = {exercise.exercise_id: exercise for exercise in (exercises or [])}

    async def get_lesson(self, lesson_id):
        return self.lessons.get(lesson_id)

    async def get_exercise(self, exercise_id):
        return self.exercises.get(exercise_id)


class FakeUnitOfWork:
    def __init__(self, curriculum, conversations) -> None:
        self.curriculum = curriculum
        self._conversations = conversations

    async def __aenter__(self):
        self.tutor_conversations = self
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get_conversation(self, conversation_id):
        return self._conversations.get(conversation_id)


class FakeTutorService:
    def __init__(self) -> None:
        self.created_contexts: list[TutorContext] = []
        self.asked: list[tuple] = []

    async def create_conversation(self, *, learner_id, context: TutorContext):
        self.created_contexts.append(context)
        return TutorConversation(
            learner_id=learner_id, context_type=context.context_type, lesson_id=context.lesson_id,
            exercise_id=context.exercise_id,
        )

    async def ask(self, *, conversation_id, question, top_k=8, context=None):
        self.asked.append((conversation_id, question, context))
        return "fake-response"


def _lesson(**overrides) -> Lesson:
    defaults = dict(
        module_id=uuid4(), code="lesson-1", title="Lesson", summary="Summary",
        content_markdown="Content", difficulty=DifficultyLevel.BEGINNER, status=LessonStatus.PUBLISHED,
        position=0, estimated_minutes=5, primary_skill_id=uuid4(),
    )
    defaults.update(overrides)
    return Lesson(**defaults)


def _exercise(lesson_id, **overrides) -> Exercise:
    defaults = dict(
        lesson_id=lesson_id, exercise_type=ExerciseType.MULTIPLE_CHOICE, prompt="Prompt",
        explanation="Explanation", difficulty=DifficultyLevel.BEGINNER, position=0,
        skill_ids=[uuid4()], maximum_score=1.0, passing_score=1.0,
    )
    defaults.update(overrides)
    return Exercise(**defaults)


@pytest.mark.asyncio
class TestCreateLessonConversation:
    async def test_creates_conversation_with_skill_ids(self) -> None:
        lesson = _lesson()
        curriculum = FakeCurriculumRepository(lessons=[lesson])
        uow_factory = lambda: FakeUnitOfWork(curriculum, {})  # noqa: E731
        tutor_service = FakeTutorService()
        service = LessonTutorService(tutor_service=tutor_service, unit_of_work_factory=uow_factory)

        await service.create_lesson_conversation(learner_id=uuid4(), lesson_id=lesson.lesson_id)

        context = tutor_service.created_contexts[0]
        assert context.context_type == TutorContextType.LESSON_HELP
        assert lesson.primary_skill_id in context.target_skill_ids

    async def test_unknown_lesson_raises(self) -> None:
        curriculum = FakeCurriculumRepository()
        uow_factory = lambda: FakeUnitOfWork(curriculum, {})  # noqa: E731
        service = LessonTutorService(tutor_service=FakeTutorService(), unit_of_work_factory=uow_factory)
        with pytest.raises(LessonNotFoundError):
            await service.create_lesson_conversation(learner_id=uuid4(), lesson_id=uuid4())


@pytest.mark.asyncio
class TestCreateExerciseHelpConversation:
    async def test_creates_conversation(self) -> None:
        lesson = _lesson()
        exercise = _exercise(lesson.lesson_id)
        curriculum = FakeCurriculumRepository(lessons=[lesson], exercises=[exercise])
        uow_factory = lambda: FakeUnitOfWork(curriculum, {})  # noqa: E731
        tutor_service = FakeTutorService()
        service = LessonTutorService(tutor_service=tutor_service, unit_of_work_factory=uow_factory)

        await service.create_exercise_help_conversation(learner_id=uuid4(), exercise_id=exercise.exercise_id)

        context = tutor_service.created_contexts[0]
        assert context.context_type == TutorContextType.EXERCISE_HELP
        assert context.exercise_id == exercise.exercise_id

    async def test_unknown_exercise_raises(self) -> None:
        curriculum = FakeCurriculumRepository()
        uow_factory = lambda: FakeUnitOfWork(curriculum, {})  # noqa: E731
        service = LessonTutorService(tutor_service=FakeTutorService(), unit_of_work_factory=uow_factory)
        with pytest.raises(ExerciseNotFoundError):
            await service.create_exercise_help_conversation(learner_id=uuid4(), exercise_id=uuid4())


@pytest.mark.asyncio
async def test_ask_passes_exercise_submitted_flag_through() -> None:
    conversation = TutorConversation(
        learner_id=uuid4(), context_type=TutorContextType.EXERCISE_HELP, exercise_id=uuid4(),
    )
    curriculum = FakeCurriculumRepository()
    conversations = {conversation.conversation_id: conversation}
    uow_factory = lambda: FakeUnitOfWork(curriculum, conversations)  # noqa: E731
    tutor_service = FakeTutorService()
    service = LessonTutorService(tutor_service=tutor_service, unit_of_work_factory=uow_factory)

    await service.ask(conversation_id=conversation.conversation_id, question="q", exercise_submitted=True)

    _conversation_id, _question, context = tutor_service.asked[0]
    assert context.structured_context["exercise_submitted"] is True
