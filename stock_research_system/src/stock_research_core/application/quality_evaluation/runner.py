"""Case-execution dispatch (spec section 5) - routes each curated case to
the correct existing-FinQuest-service entry point via
`EvaluationCaseExecutorPort`, by its `context_type`. Never duplicates
retrieval, generation, guardrails, or Coach routing itself.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from stock_research_core.application.quality_evaluation.models import (
    EvaluationCaseExecutionInput,
    EvaluationCaseExecutionResult,
)
from stock_research_core.application.quality_evaluation.ports import EvaluationCaseExecutorPort
from stock_research_core.domain.quality_evaluation.enums import EvaluationCaseContextType
from stock_research_core.domain.quality_evaluation.models import QualityEvaluationCase


class QualityEvaluationRunner:
    def __init__(self, *, executor: EvaluationCaseExecutorPort) -> None:
        self._executor = executor
        self._handlers: dict[
            EvaluationCaseContextType, Callable[[EvaluationCaseExecutionInput], Awaitable[EvaluationCaseExecutionResult]]
        ] = {
            EvaluationCaseContextType.GENERAL_RAG: executor.execute_general_rag,
            EvaluationCaseContextType.LESSON: executor.execute_lesson_tutor,
            EvaluationCaseContextType.EXERCISE_BEFORE_SUBMISSION: executor.execute_exercise_tutor,
            EvaluationCaseContextType.EXERCISE_AFTER_SUBMISSION: executor.execute_exercise_tutor,
            EvaluationCaseContextType.SCENARIO_BEFORE_REVEAL: executor.execute_scenario_before_tutor,
            EvaluationCaseContextType.SCENARIO_AFTER_REVEAL: executor.execute_scenario_after_tutor,
            EvaluationCaseContextType.PORTFOLIO: executor.execute_portfolio_tutor,
            EvaluationCaseContextType.COACH: executor.execute_coach_turn,
        }

    async def execute_case(self, case: QualityEvaluationCase) -> EvaluationCaseExecutionResult:
        handler = self._handlers.get(case.context_type)
        if handler is None:
            raise ValueError(f"No executor registered for context_type {case.context_type!r}")
        execution_input = EvaluationCaseExecutionInput(
            case_id=case.case_id, context_type=case.context_type, user_input=case.user_input,
        )
        return await handler(execution_input)
