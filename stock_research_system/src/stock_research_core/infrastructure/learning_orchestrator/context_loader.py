"""`SqlAlchemyLearningContextLoader`: the only concrete implementation of
`LearningContextLoaderPort`.

Every method here reuses an existing FinQuest application service or
Unit-of-Work repository (`LearningService.get_learner_dashboard`,
`uow.mastery`/`uow.progress`/`uow.misconceptions`/`uow.review_schedules`,
`uow.curriculum`, `uow.market_scenarios`/`uow.scenario_submissions`,
`VirtualPortfolioService.get_overview`) and returns only bounded, plain,
JSON-serializable dicts - never a raw ORM row, a full document, or a
learner-owned resource belonging to someone else. Ownership-mismatched
lookups raise the same not-found errors those services already raise
elsewhere in the API, so a learner probing another learner's IDs gets
an identical 404 here as anywhere else in FinQuest.
"""

from __future__ import annotations

from typing import Any, Callable
from uuid import UUID

from stock_research_core.application.exceptions import (
    ExerciseNotFoundError,
    LessonNotFoundError,
    MarketScenarioNotFoundError,
    ScenarioSubmissionNotFoundError,
    VirtualPortfolioNotFoundError,
)
from stock_research_core.application.learning.service import LearningService
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.application.virtual_portfolio.service import VirtualPortfolioService
from stock_research_core.domain.adaptive_learning.enums import ReviewScheduleStatus
from stock_research_core.domain.models import utc_now

_MAX_SUMMARY_ITEMS = 50


class SqlAlchemyLearningContextLoader:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWorkPort], learning_service: LearningService,
        portfolio_service: VirtualPortfolioService,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._learning_service = learning_service
        self._portfolio_service = portfolio_service

    async def load_dashboard(self, learner_id: UUID) -> dict[str, Any]:
        dashboard = await self._learning_service.get_learner_dashboard(learner_id)
        return {
            "active_path_title": dashboard.active_path.title if dashboard.active_path else None,
            "current_lesson_title": dashboard.current_lesson.title if dashboard.current_lesson else None,
            "completed_lessons": dashboard.completed_lessons, "total_lessons": dashboard.total_lessons,
            "current_streak_days": dashboard.current_streak_days, "total_xp": dashboard.total_xp,
        }

    async def load_mastery_summary(self, learner_id: UUID) -> list[dict[str, Any]]:
        async with self._unit_of_work_factory() as uow:
            mastery_rows = await uow.mastery.list_for_learner(learner_id)
        return [
            {
                "skill_id": str(row.skill_id), "mastery_score": row.mastery_score,
                "mastery_level": row.mastery_level.value, "total_attempts": row.total_attempts,
            }
            for row in mastery_rows[:_MAX_SUMMARY_ITEMS]
        ]

    async def load_progress_summary(self, learner_id: UUID) -> list[dict[str, Any]]:
        async with self._unit_of_work_factory() as uow:
            progress_rows = await uow.progress.list_for_learner(learner_id)
        return [
            {
                "lesson_id": str(row.lesson_id) if row.lesson_id else None,
                "path_id": str(row.path_id) if row.path_id else None,
                "status": row.status.value, "completion_percentage": row.completion_percentage,
            }
            for row in progress_rows[:_MAX_SUMMARY_ITEMS]
        ]

    async def load_active_misconceptions(self, learner_id: UUID) -> list[dict[str, Any]]:
        async with self._unit_of_work_factory() as uow:
            misconceptions = await uow.misconceptions.list_active(learner_id)
        return [
            {"skill_id": str(row.skill_id), "code": row.code, "description": row.description}
            for row in misconceptions[:_MAX_SUMMARY_ITEMS]
        ]

    async def load_due_review_summary(self, learner_id: UUID) -> list[dict[str, Any]]:
        now = utc_now()
        async with self._unit_of_work_factory() as uow:
            schedules = await uow.review_schedules.list_for_learner(learner_id)
        due = [
            schedule for schedule in schedules
            if schedule.status == ReviewScheduleStatus.SCHEDULED
            and schedule.next_review_at is not None and schedule.next_review_at <= now
        ]
        return [
            {"skill_id": str(schedule.skill_id), "next_review_at": schedule.next_review_at.isoformat()}
            for schedule in due[:_MAX_SUMMARY_ITEMS]
        ]

    async def load_lesson_metadata(self, *, learner_id: UUID, lesson_id: UUID) -> dict[str, Any]:
        async with self._unit_of_work_factory() as uow:
            lesson = await uow.curriculum.get_lesson(lesson_id)
        if lesson is None:
            raise LessonNotFoundError(f"No lesson found with id '{lesson_id}'.")
        return {
            "lesson_id": str(lesson.lesson_id), "title": lesson.title, "summary": lesson.summary,
            "difficulty": lesson.difficulty.value, "status": lesson.status.value,
        }

    async def load_exercise_metadata(self, *, learner_id: UUID, exercise_id: UUID) -> dict[str, Any]:
        async with self._unit_of_work_factory() as uow:
            exercise = await uow.curriculum.get_exercise(exercise_id)
            if exercise is None:
                raise ExerciseNotFoundError(f"No exercise found with id '{exercise_id}'.")
            attempts = await uow.attempts.list_attempts(learner_id, exercise_id)
        submitted = any(attempt.submitted_at is not None for attempt in attempts)
        return {
            "exercise_id": str(exercise.exercise_id), "exercise_type": exercise.exercise_type.value,
            "difficulty": exercise.difficulty.value, "submitted": submitted,
        }

    async def load_scenario_metadata(
        self, *, learner_id: UUID, scenario_id: UUID, submission_id: UUID | None
    ) -> dict[str, Any]:
        async with self._unit_of_work_factory() as uow:
            scenario = await uow.market_scenarios.get(scenario_id)
            if scenario is None:
                raise MarketScenarioNotFoundError(f"No scenario found with id '{scenario_id}'.")

            submission = None
            if submission_id is not None:
                submission = await uow.scenario_submissions.get(submission_id)
                if submission is None or submission.scenario_id != scenario_id or submission.learner_id != learner_id:
                    raise ScenarioSubmissionNotFoundError(f"No submission found with id '{submission_id}'.")
            else:
                learner_submissions = [
                    row for row in await uow.scenario_submissions.list_for_learner(learner_id)
                    if row.scenario_id == scenario_id
                ]
                submission = max(learner_submissions, key=lambda row: row.submission_id, default=None)

        return {
            "scenario_id": str(scenario.scenario_id), "title": scenario.title,
            "scenario_type": scenario.scenario_type.value,
            "reveal_status": submission.reveal_status.value if submission else None,
            "submission_id": str(submission.submission_id) if submission else None,
        }

    async def load_portfolio_overview(self, *, learner_id: UUID, portfolio_id: UUID) -> dict[str, Any]:
        overview = await self._portfolio_service.get_overview(portfolio_id)
        if overview.portfolio.learner_id != learner_id:
            raise VirtualPortfolioNotFoundError(f"No virtual portfolio '{portfolio_id}' found for learner '{learner_id}'.")

        valuation = overview.latest_valuation
        return {
            "portfolio_id": str(overview.portfolio.portfolio_id), "position_count": len(overview.holdings),
            "cash_weight": valuation.cash_weight if valuation else None,
            "diversification_score": valuation.diversification_score if valuation else None,
            "total_return": valuation.total_return if valuation else None,
        }
