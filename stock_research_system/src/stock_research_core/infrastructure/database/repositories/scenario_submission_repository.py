"""SQLAlchemy repository for `ScenarioSubmission` persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.market_scenarios.models import ScenarioSubmission
from stock_research_core.infrastructure.database.mappers.market_scenario_mappers import (
    scenario_submission_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.scenario_submission import (
    ScenarioSubmissionFeedbackCodeORM,
    ScenarioSubmissionORM,
)


class SqlAlchemyScenarioSubmissionRepository:
    """Persists and queries `ScenarioSubmission` rows. Unique per
    `exercise_attempt_id` (enforced by a database unique constraint)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, submission: ScenarioSubmission) -> ScenarioSubmission:
        row = ScenarioSubmissionORM(
            submission_id=submission.submission_id,
            scenario_id=submission.scenario_id,
            learner_id=submission.learner_id,
            exercise_attempt_id=submission.exercise_attempt_id,
            selected_option_id=submission.selected_option_id,
            status=submission.status.value,
            confidence_level=submission.confidence_level.value if submission.confidence_level else None,
            learner_rationale=submission.learner_rationale,
            decision_quality_score=submission.decision_quality_score,
            outcome_alignment_score=submission.outcome_alignment_score,
            total_display_score=submission.total_display_score,
            decision_quality=submission.decision_quality.value if submission.decision_quality else None,
            feedback_text=submission.feedback_text,
            reveal_status=submission.reveal_status.value,
            started_at=submission.started_at,
            submitted_at=submission.submitted_at,
            graded_at=submission.graded_at,
            revealed_at=submission.revealed_at,
            rubric_version=submission.rubric_version,
            outcome_calculation_version=submission.outcome_calculation_version,
        )
        self._session.add(row)
        for code in submission.feedback_codes:
            self._session.add(
                ScenarioSubmissionFeedbackCodeORM(
                    submission_id=submission.submission_id, feedback_code=code.value
                )
            )
        await self._session.flush()
        return await self._to_domain(row)

    async def get(self, submission_id: UUID) -> ScenarioSubmission | None:
        row = await self._session.get(ScenarioSubmissionORM, submission_id)
        return await self._to_domain(row) if row is not None else None

    async def get_by_attempt(self, exercise_attempt_id: UUID) -> ScenarioSubmission | None:
        result = await self._session.execute(
            select(ScenarioSubmissionORM).where(
                ScenarioSubmissionORM.exercise_attempt_id == exercise_attempt_id
            )
        )
        row = result.scalar_one_or_none()
        return await self._to_domain(row) if row is not None else None

    async def update(self, submission: ScenarioSubmission) -> ScenarioSubmission:
        row = await self._session.get(ScenarioSubmissionORM, submission.submission_id)
        if row is None:
            raise PersistenceError(f"No scenario submission found with id '{submission.submission_id}'.")

        row.selected_option_id = submission.selected_option_id
        row.status = submission.status.value
        row.confidence_level = submission.confidence_level.value if submission.confidence_level else None
        row.learner_rationale = submission.learner_rationale
        row.decision_quality_score = submission.decision_quality_score
        row.outcome_alignment_score = submission.outcome_alignment_score
        row.total_display_score = submission.total_display_score
        row.decision_quality = submission.decision_quality.value if submission.decision_quality else None
        row.feedback_text = submission.feedback_text
        row.reveal_status = submission.reveal_status.value
        row.submitted_at = submission.submitted_at
        row.graded_at = submission.graded_at
        row.revealed_at = submission.revealed_at
        row.rubric_version = submission.rubric_version
        row.outcome_calculation_version = submission.outcome_calculation_version

        await self._session.execute(
            delete(ScenarioSubmissionFeedbackCodeORM).where(
                ScenarioSubmissionFeedbackCodeORM.submission_id == submission.submission_id
            )
        )
        for code in submission.feedback_codes:
            self._session.add(
                ScenarioSubmissionFeedbackCodeORM(
                    submission_id=submission.submission_id, feedback_code=code.value
                )
            )
        await self._session.flush()
        # `updated_at` has a client-side `onupdate=func.now()` default, so
        # after flush() it is marked expired rather than populated -
        # `refresh()` reloads it in an async-safe way before `_to_domain`
        # (a plain synchronous attribute access) touches it.
        await self._session.refresh(row)
        return await self._to_domain(row)

    async def list_for_learner(self, learner_id: UUID) -> list[ScenarioSubmission]:
        result = await self._session.execute(
            select(ScenarioSubmissionORM)
            .where(ScenarioSubmissionORM.learner_id == learner_id)
            .order_by(ScenarioSubmissionORM.created_at.asc())
        )
        rows = result.scalars().all()
        return [await self._to_domain(row) for row in rows]

    async def _to_domain(self, row: ScenarioSubmissionORM) -> ScenarioSubmission:
        code_result = await self._session.execute(
            select(ScenarioSubmissionFeedbackCodeORM.feedback_code).where(
                ScenarioSubmissionFeedbackCodeORM.submission_id == row.submission_id
            )
        )
        return scenario_submission_orm_to_domain(row, list(code_result.scalars().all()))
