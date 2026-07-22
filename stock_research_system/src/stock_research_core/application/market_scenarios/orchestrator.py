"""Thin orchestration layer composing `LearningService`,
`AdaptiveLearningService`, and `HistoricalMarketScenarioService`.

Grading, mastery-update, and adaptive-session logic is never duplicated
here - it always flows through the existing, already-tested
`HistoricalMarketScenarioService.submit_decision` (which itself reuses
`LearningService.submit_externally_graded_answer`) and
`AdaptiveLearningService.record_completed_activity`.
"""

from __future__ import annotations

from uuid import UUID

from stock_research_core.application.adaptive_learning.service import AdaptiveLearningService
from stock_research_core.application.exceptions import InvalidScenarioStateError
from stock_research_core.application.learning.service import LearningService
from stock_research_core.application.market_scenarios.models import (
    LearnerScenarioView,
    ScenarioReveal,
    ScenarioSubmissionResult,
)
from stock_research_core.application.market_scenarios.service import HistoricalMarketScenarioService
from stock_research_core.domain.learning.enums import ConfidenceLevel


class MarketScenarioLearningOrchestrator:
    """Composes the existing `LearningService`/`AdaptiveLearningService`
    with `HistoricalMarketScenarioService`, one bounded transaction per
    underlying service - the same pattern already used by
    `AdaptiveLearningOrchestrator`.
    """

    def __init__(
        self,
        learning_service: LearningService,
        adaptive_learning_service: AdaptiveLearningService,
        market_scenario_service: HistoricalMarketScenarioService,
    ) -> None:
        self._learning_service = learning_service
        self._adaptive_learning_service = adaptive_learning_service
        self._market_scenario_service = market_scenario_service

    async def start_recommended_scenario(
        self, *, adaptive_decision_id: UUID, confidence_level: ConfidenceLevel | None = None
    ) -> LearnerScenarioView:
        attempt = await self._adaptive_learning_service.start_recommended_exercise(
            decision_id=adaptive_decision_id, confidence_level=confidence_level
        )

        scenario = await self._market_scenario_service.get_scenario_for_exercise(attempt.exercise_id)
        if scenario is None:
            raise InvalidScenarioStateError(
                f"No published scenario is linked to exercise '{attempt.exercise_id}'."
            )

        # Idempotent: `start_scenario` itself refuses to duplicate an
        # active submission for the same attempt.
        await self._market_scenario_service.start_scenario(
            learner_id=attempt.learner_id,
            scenario_id=scenario.scenario_id,
            exercise_attempt_id=attempt.attempt_id,
        )

        return await self._market_scenario_service.get_learner_view(
            learner_id=attempt.learner_id, scenario_id=scenario.scenario_id
        )

    async def submit_recommended_scenario_decision(
        self,
        *,
        adaptive_decision_id: UUID,
        selected_option_id: UUID,
        confidence_level: ConfidenceLevel | None = None,
        learner_rationale: str | None = None,
    ) -> ScenarioSubmissionResult:
        attempt_id = await self._adaptive_learning_service.get_attempt_id_for_decision(
            decision_id=adaptive_decision_id
        )
        submission = await self._market_scenario_service.get_submission_for_attempt(attempt_id)
        if submission is None:
            raise InvalidScenarioStateError(
                f"No scenario submission found for attempt '{attempt_id}'; call "
                "start_recommended_scenario first."
            )

        result = await self._market_scenario_service.submit_decision(
            submission_id=submission.submission_id,
            selected_option_id=selected_option_id,
            confidence_level=confidence_level,
            learner_rationale=learner_rationale,
        )

        await self._adaptive_learning_service.record_completed_activity(
            decision_id=adaptive_decision_id,
            learning_activity_result=result.learning_activity_result,
        )

        return result

    async def reveal_recommended_scenario(self, *, adaptive_decision_id: UUID) -> ScenarioReveal:
        attempt_id = await self._adaptive_learning_service.get_attempt_id_for_decision(
            decision_id=adaptive_decision_id
        )
        submission = await self._market_scenario_service.get_submission_for_attempt(attempt_id)
        if submission is None:
            raise InvalidScenarioStateError(f"No scenario submission found for attempt '{attempt_id}'.")
        return await self._market_scenario_service.reveal_outcome(submission_id=submission.submission_id)
