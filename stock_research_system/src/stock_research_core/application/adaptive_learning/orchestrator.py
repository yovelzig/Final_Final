"""Thin orchestration layer composing `LearningService` and `AdaptiveLearningService`.

Grading and mastery-update logic is never duplicated here - it always
flows through the existing, already-tested `LearningService.submit_answer`.
"""

from __future__ import annotations

from uuid import UUID

from stock_research_core.application.adaptive_learning.models import SessionSummary
from stock_research_core.application.adaptive_learning.service import AdaptiveLearningService
from stock_research_core.application.exceptions import InvalidDecisionStateError
from stock_research_core.application.learning.service import LearningService
from stock_research_core.domain.learning.models import ExerciseAnswer


class AdaptiveLearningOrchestrator:
    """Composes the existing `LearningService` with `AdaptiveLearningService`.

    Two bounded transactions are used - one per underlying service -
    rather than a single shared Unit of Work: each service owns its own
    persistence boundary, and forcing them to share one transaction
    would require leaking SQLAlchemy session details across a Protocol
    boundary that intentionally hides them.

    Documented compensation: if grading succeeds (the answer, attempt,
    mastery, and progress are already committed) but recording the
    adaptive outcome fails afterward, that failure is **not**
    compensated by undoing the grade - the grade is independently
    correct and valuable on its own. Instead, the adaptive decision and
    session activity are simply left in their prior state (never
    falsely marked `COMPLETED`), and `record_completed_activity` is
    idempotent with respect to the already-graded attempt, so retrying
    `submit_recommended_answer` is always safe.
    """

    def __init__(
        self,
        learning_service: LearningService,
        adaptive_learning_service: AdaptiveLearningService,
    ) -> None:
        self._learning_service = learning_service
        self._adaptive_learning_service = adaptive_learning_service

    async def submit_recommended_answer(
        self, *, decision_id: UUID, answer: ExerciseAnswer
    ) -> SessionSummary:
        attempt_id = await self._adaptive_learning_service.get_attempt_id_for_decision(
            decision_id=decision_id
        )
        if answer.attempt_id != attempt_id:
            raise InvalidDecisionStateError(
                "answer.attempt_id does not match the attempt started for this decision."
            )

        learning_activity_result = await self._learning_service.submit_answer(
            attempt_id=attempt_id, answer=answer
        )

        return await self._adaptive_learning_service.record_completed_activity(
            decision_id=decision_id, learning_activity_result=learning_activity_result
        )
