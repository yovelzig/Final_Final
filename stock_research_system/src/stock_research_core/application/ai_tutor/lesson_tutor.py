"""`LessonTutorService`: tutor conversations scoped to a lesson or exercise.

Composes `GroundedAITutorService`. For `EXERCISE_HELP`, correct-option
leakage is prevented structurally by
`HybridKnowledgeRetriever._apply_exercise_answer_leakage_guard`
(retrieval never surfaces `CURRICULUM_EXERCISE_EXPLANATION` content
unless `exercise_submitted=True`) - this service's only responsibility
is to pass that flag through accurately.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from stock_research_core.application.ai_tutor.models import TutorContext, TutorResponse
from stock_research_core.application.ai_tutor.service import GroundedAITutorService
from stock_research_core.application.exceptions import (
    ExerciseNotFoundError,
    LessonNotFoundError,
    TutorConversationNotFoundError,
)
from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.domain.ai_tutor.models import TutorConversation
from stock_research_core.domain.models import utc_now

Clock = Callable[[], datetime]


class LessonTutorService:
    """Creates and drives lesson/exercise-scoped tutor conversations."""

    def __init__(
        self, *, tutor_service: GroundedAITutorService, unit_of_work_factory: Callable[[], Any], clock: Clock = utc_now
    ) -> None:
        self._tutor_service = tutor_service
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock

    async def create_lesson_conversation(self, *, learner_id: UUID, lesson_id: UUID) -> TutorConversation:
        async with self._unit_of_work_factory() as uow:
            lesson = await uow.curriculum.get_lesson(lesson_id)
            if lesson is None:
                raise LessonNotFoundError(f"No lesson found with id '{lesson_id}'.")

        context = TutorContext(
            context_type=TutorContextType.LESSON_HELP,
            learner_id=learner_id,
            lesson_id=lesson_id,
            target_skill_ids=list(dict.fromkeys([lesson.primary_skill_id, *lesson.secondary_skill_ids])),
        )
        return await self._tutor_service.create_conversation(learner_id=learner_id, context=context)

    async def create_exercise_help_conversation(self, *, learner_id: UUID, exercise_id: UUID) -> TutorConversation:
        async with self._unit_of_work_factory() as uow:
            exercise = await uow.curriculum.get_exercise(exercise_id)
            if exercise is None:
                raise ExerciseNotFoundError(f"No exercise found with id '{exercise_id}'.")

        context = TutorContext(
            context_type=TutorContextType.EXERCISE_HELP,
            learner_id=learner_id,
            lesson_id=exercise.lesson_id,
            exercise_id=exercise_id,
            target_skill_ids=list(dict.fromkeys(exercise.skill_ids)),
        )
        return await self._tutor_service.create_conversation(learner_id=learner_id, context=context)

    async def ask(
        self, *, conversation_id: UUID, question: str, exercise_submitted: bool = False, top_k: int = 8
    ) -> TutorResponse:
        async with self._unit_of_work_factory() as uow:
            conversation = await uow.tutor_conversations.get_conversation(conversation_id)
        if conversation is None:
            raise TutorConversationNotFoundError(f"No tutor conversation found with id '{conversation_id}'.")

        structured_context: dict[str, Any] = {}
        if conversation.context_type == TutorContextType.EXERCISE_HELP:
            structured_context["exercise_submitted"] = exercise_submitted

        context = TutorContext(
            context_type=conversation.context_type,
            learner_id=conversation.learner_id,
            lesson_id=conversation.lesson_id,
            exercise_id=conversation.exercise_id,
            structured_context=structured_context,
        )
        return await self._tutor_service.ask(
            conversation_id=conversation_id, question=question, top_k=top_k, context=context
        )
