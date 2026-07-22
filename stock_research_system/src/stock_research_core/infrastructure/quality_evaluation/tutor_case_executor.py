"""The real `EvaluationCaseExecutorPort` implementation for general
grounded-RAG cases - invokes the actual, production
`GroundedAITutorService.ask()` (never a re-implementation of retrieval,
generation, or guardrails), under a dedicated evaluation learner/
conversation so nothing here ever touches a real learner's history
(spec section 16).

Scope note: only `execute_general_rag` is wired to a real service this
phase - `finquest-rag-core-v1`/`finquest-safety-v1` (both
`GENERAL_RAG`-context suites) are fully exercisable end to end. The
lesson/exercise/scenario/portfolio/Coach executor methods raise
`NotImplementedError` rather than silently returning fabricated
results; wiring them up is a follow-up (each needs its own tutor
service's specific required context - `lesson_id`/`scenario_id`/etc -
plumbed through `EvaluationCaseExecutionInput.context_references`).
"""

from __future__ import annotations

from typing import Callable
from uuid import UUID, uuid5

from stock_research_core.application.ai_tutor.models import TutorContext
from stock_research_core.application.ai_tutor.service import GroundedAITutorService
from stock_research_core.application.persistence.ports import UnitOfWorkPort

#: A fixed, deterministic learner id reserved for evaluation fixtures -
#: never a real learner. Seeded once (idempotently) via
#: `scripts/seed_quality_evaluation_fixtures.py`; every evaluation
#: conversation is created and closed under this id, so it never mixes
#: with genuine learner activity (spec section 16).
EVALUATION_FIXTURE_LEARNER_ID: UUID = uuid5(UUID("00000000-0000-0000-0000-000000000000"), "finquest-quality-evaluation-fixture-learner")
from stock_research_core.application.quality_evaluation.models import (
    EvaluationCaseExecutionInput,
    EvaluationCaseExecutionResult,
)
from stock_research_core.domain.ai_tutor.enums import TutorContextType


class TutorGroundedCaseExecutor:
    def __init__(
        self, *, tutor_service: GroundedAITutorService, unit_of_work_factory: Callable[[], UnitOfWorkPort],
        evaluation_learner_id: UUID,
    ) -> None:
        self._tutor_service = tutor_service
        self._unit_of_work_factory = unit_of_work_factory
        self._evaluation_learner_id = evaluation_learner_id

    async def execute_general_rag(self, case: EvaluationCaseExecutionInput) -> EvaluationCaseExecutionResult:
        conversation = await self._tutor_service.create_conversation(
            learner_id=self._evaluation_learner_id,
            context=TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=self._evaluation_learner_id),
        )
        try:
            response = await self._tutor_service.ask(conversation_id=conversation.conversation_id, question=case.user_input)

            retrieved_context_ids: list[UUID] = []
            if response.answer.retrieval_run_id is not None:
                async with self._unit_of_work_factory() as uow:
                    retrieval_run = await uow.tutor_retrieval.get_run(response.answer.retrieval_run_id)
                if retrieval_run is not None:
                    retrieved_context_ids = list(retrieval_run.returned_chunk_ids)

            async with self._unit_of_work_factory() as uow:
                citations = await uow.tutor_answers.list_citations_for_answer(response.answer.answer_id)
            citation_chunk_ids = [citation.chunk_id for citation in sorted(citations, key=lambda c: c.citation_number)]

            return EvaluationCaseExecutionResult(
                case_id=case.case_id, generated_response=response.answer.answer_markdown,
                retrieved_context_ids=retrieved_context_ids, citation_chunk_ids=citation_chunk_ids,
                observed_guardrail_category=response.guardrail.request_category,
            )
        finally:
            # Evaluation conversations are single-use fixtures, never a
            # real learner's ongoing history - close it immediately so it
            # cannot be mistaken for one in any conversation listing.
            await self._tutor_service.close_conversation(conversation.conversation_id)

    async def execute_lesson_tutor(self, case: EvaluationCaseExecutionInput) -> EvaluationCaseExecutionResult:
        raise NotImplementedError("Lesson-tutor case execution is not wired yet - see module docstring.")

    async def execute_exercise_tutor(self, case: EvaluationCaseExecutionInput) -> EvaluationCaseExecutionResult:
        raise NotImplementedError("Exercise-tutor case execution is not wired yet - see module docstring.")

    async def execute_scenario_before_tutor(self, case: EvaluationCaseExecutionInput) -> EvaluationCaseExecutionResult:
        raise NotImplementedError("Scenario-before-tutor case execution is not wired yet - see module docstring.")

    async def execute_scenario_after_tutor(self, case: EvaluationCaseExecutionInput) -> EvaluationCaseExecutionResult:
        raise NotImplementedError("Scenario-after-tutor case execution is not wired yet - see module docstring.")

    async def execute_portfolio_tutor(self, case: EvaluationCaseExecutionInput) -> EvaluationCaseExecutionResult:
        raise NotImplementedError("Portfolio-tutor case execution is not wired yet - see module docstring.")

    async def execute_coach_turn(self, case: EvaluationCaseExecutionInput) -> EvaluationCaseExecutionResult:
        raise NotImplementedError("Coach case execution is not wired yet - see module docstring.")
