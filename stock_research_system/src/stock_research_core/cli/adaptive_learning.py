"""CLI for the FinQuest adaptive learning engine.

Start a daily practice session (PowerShell):

    python -m stock_research_core.cli.adaptive_learning --learner-id <UUID> --start-session

Get the next recommendation in a session:

    python -m stock_research_core.cli.adaptive_learning --learner-id <UUID> --session-id <UUID> --next

Start a diagnostic assessment:

    python -m stock_research_core.cli.adaptive_learning --learner-id <UUID> --start-diagnostic --maximum-items 6

Check a diagnostic assessment's status:

    python -m stock_research_core.cli.adaptive_learning --diagnostic-id <UUID> --diagnostic-status

List reviews currently due for a learner:

    python -m stock_research_core.cli.adaptive_learning --learner-id <UUID> --due-reviews

Complete a session:

    python -m stock_research_core.cli.adaptive_learning --session-id <UUID> --complete-session

This module is a composition root: it is the one place outside the
infrastructure layer allowed to import concrete adapters directly.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from stock_research_core.application.adaptive_learning.policies import (
    DeterministicReviewSchedulingPolicy,
    RuleBasedAdaptivePolicy,
    RuleBasedDiagnosticPolicy,
    RuleBasedDifficultyPolicy,
)
from stock_research_core.application.adaptive_learning.service import AdaptiveLearningService
from stock_research_core.application.exceptions import StockResearchError
from stock_research_core.domain.adaptive_learning.enums import LearningSessionType
from stock_research_core.domain.models import utc_now
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stock_research_core.cli.adaptive_learning",
        description="Drive the FinQuest adaptive learning engine: sessions, recommendations, diagnostics, and reviews.",
    )
    parser.add_argument("--learner-id", metavar="UUID", default=None, help="Target learner ID")
    parser.add_argument("--session-id", metavar="UUID", default=None, help="Target session ID")
    parser.add_argument(
        "--diagnostic-id", metavar="UUID", default=None, help="Target diagnostic assessment ID"
    )

    parser.add_argument(
        "--start-session", action="store_true", help="Start (or reuse) a learning session"
    )
    parser.add_argument(
        "--session-type",
        default=LearningSessionType.DAILY_PRACTICE.value,
        choices=[member.value for member in LearningSessionType],
        help="Session type for --start-session (default: DAILY_PRACTICE)",
    )
    parser.add_argument(
        "--goal-minutes", type=int, default=None, help="Override the learner's default daily goal"
    )
    parser.add_argument(
        "--next", dest="next_recommendation", action="store_true", help="Get the next recommendation"
    )
    parser.add_argument(
        "--complete-session", action="store_true", help="Mark a session as completed"
    )
    parser.add_argument(
        "--start-diagnostic", action="store_true", help="Start a diagnostic assessment"
    )
    parser.add_argument(
        "--maximum-items", type=int, default=10, help="Maximum items for --start-diagnostic"
    )
    parser.add_argument(
        "--diagnostic-status", action="store_true", help="Print status for --diagnostic-id"
    )
    parser.add_argument(
        "--due-reviews", action="store_true", help="List reviews currently due for a learner"
    )
    return parser


def _build_service(unit_of_work_factory) -> AdaptiveLearningService:  # noqa: ANN001
    return AdaptiveLearningService(
        unit_of_work_factory=unit_of_work_factory,
        adaptive_policy=RuleBasedAdaptivePolicy(),
        difficulty_policy=RuleBasedDifficultyPolicy(),
        review_policy=DeterministicReviewSchedulingPolicy(),
        diagnostic_policy=RuleBasedDiagnosticPolicy(),
    )


async def _start_session(
    service: AdaptiveLearningService, learner_id: UUID, session_type: str, goal_minutes: int | None
) -> None:
    session = await service.start_session(
        learner_id=learner_id,
        session_type=LearningSessionType(session_type),
        goal_minutes=goal_minutes,
    )
    print("Session:")
    print(f"  Session ID:   {session.session_id}")
    print(f"  Type:         {session.session_type.value}")
    print(f"  Status:       {session.status.value}")
    print(f"  Goal minutes: {session.goal_minutes}")


async def _next_recommendation(
    service: AdaptiveLearningService, learner_id: UUID, session_id: UUID
) -> None:
    recommendation = await service.recommend_next(learner_id=learner_id, session_id=session_id)
    decision = recommendation.decision
    print("Recommendation:")
    print(f"  Decision ID:  {decision.decision_id}")
    print(f"  Type:         {decision.recommendation_type.value}")
    print(f"  Priority:     {decision.priority_score:.4f}")
    print(f"  Policy:       {decision.policy_version}")
    print(f"  Reasons:      {', '.join(reason.value for reason in decision.reason_codes) or 'none'}")
    print(f"  Explanation:  {decision.explanation}")
    if recommendation.exercise is not None:
        print(f"  Exercise ID:  {recommendation.exercise.exercise_id}")
        print(f"  Prompt:       {recommendation.exercise.prompt}")
    if decision.recommended_difficulty_score is not None:
        print(f"  Difficulty:   {decision.recommended_difficulty_score:.4f}")


async def _complete_session(service: AdaptiveLearningService, session_id: UUID) -> None:
    summary = await service.complete_session(session_id=session_id)
    print("Session summary:")
    print(f"  Session ID:        {summary.session.session_id}")
    print(f"  Status:             {summary.session.status.value}")
    print(f"  Recommended items:  {summary.session.recommended_item_count}")
    print(f"  Completed items:    {summary.session.completed_item_count}")
    print(f"  Correct items:      {summary.session.correct_item_count}")
    print(f"  Score:               {summary.session.total_score}/{summary.session.maximum_score}")


async def _start_diagnostic(
    service: AdaptiveLearningService, learner_id: UUID, maximum_items: int
) -> None:
    summary = await service.start_diagnostic(learner_id=learner_id, maximum_items=maximum_items)
    print("Diagnostic assessment started:")
    print(f"  Assessment ID: {summary.assessment.assessment_id}")
    print(f"  Status:        {summary.assessment.status.value}")
    print(f"  Items:         {len(summary.items)}")
    for item in summary.items:
        print(f"    - item {item.item_id}: exercise {item.exercise_id}")


async def _print_diagnostic_status(unit_of_work_factory, diagnostic_id: UUID) -> None:  # noqa: ANN001
    async with unit_of_work_factory() as uow:
        assessment = await uow.diagnostics.get_assessment(diagnostic_id)
        if assessment is None:
            print(f"error: no diagnostic assessment found with id '{diagnostic_id}'", file=sys.stderr)
            return
        items = await uow.diagnostics.list_items(diagnostic_id)

    completed = sum(1 for item in items if item.completed_at is not None)
    print("Diagnostic assessment status:")
    print(f"  Assessment ID: {assessment.assessment_id}")
    print(f"  Status:        {assessment.status.value}")
    print(f"  Skills:        {len(assessment.skill_ids)}")
    print(f"  Items:         {completed}/{len(items)} completed")
    for item in items:
        state = "completed" if item.completed_at is not None else "pending"
        score = f", score={item.normalized_score:.2f}" if item.normalized_score is not None else ""
        print(f"    - item {item.item_id} (position {item.position}): {state}{score}")


async def _print_due_reviews(unit_of_work_factory, learner_id: UUID) -> None:  # noqa: ANN001
    now = utc_now()
    async with unit_of_work_factory() as uow:
        due_schedules = await uow.review_schedules.list_due(learner_id, now)

    print(f"Reviews due for learner {learner_id}:")
    if not due_schedules:
        print("  none due")
        return
    for schedule in due_schedules:
        print(
            f"  - skill {schedule.skill_id}: status={schedule.status.value}, "
            f"next_review_at={schedule.next_review_at}, ease_factor={schedule.ease_factor}"
        )


async def _run(args: argparse.Namespace) -> int:
    has_action = any(
        [
            args.start_session,
            args.next_recommendation,
            args.complete_session,
            args.start_diagnostic,
            args.diagnostic_status,
            args.due_reviews,
        ]
    )
    if not has_action:
        print(
            "error: specify one of --start-session, --next, --complete-session, "
            "--start-diagnostic, --diagnostic-status, or --due-reviews",
            file=sys.stderr,
        )
        return 2

    def _parse_uuid(raw: str, label: str) -> UUID | None:
        try:
            return UUID(raw)
        except ValueError:
            print(f"error: '{raw}' is not a valid UUID for {label}", file=sys.stderr)
            return None

    settings = DatabaseSettings()
    engine = create_database_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        unit_of_work_factory = lambda: SqlAlchemyUnitOfWork(session_factory)  # noqa: E731
        service = _build_service(unit_of_work_factory)

        if args.start_session:
            if args.learner_id is None:
                print("error: --start-session requires --learner-id", file=sys.stderr)
                return 2
            learner_id = _parse_uuid(args.learner_id, "--learner-id")
            if learner_id is None:
                return 2
            await _start_session(service, learner_id, args.session_type, args.goal_minutes)

        if args.next_recommendation:
            if args.learner_id is None or args.session_id is None:
                print("error: --next requires --learner-id and --session-id", file=sys.stderr)
                return 2
            learner_id = _parse_uuid(args.learner_id, "--learner-id")
            session_id = _parse_uuid(args.session_id, "--session-id")
            if learner_id is None or session_id is None:
                return 2
            await _next_recommendation(service, learner_id, session_id)

        if args.complete_session:
            if args.session_id is None:
                print("error: --complete-session requires --session-id", file=sys.stderr)
                return 2
            session_id = _parse_uuid(args.session_id, "--session-id")
            if session_id is None:
                return 2
            await _complete_session(service, session_id)

        if args.start_diagnostic:
            if args.learner_id is None:
                print("error: --start-diagnostic requires --learner-id", file=sys.stderr)
                return 2
            learner_id = _parse_uuid(args.learner_id, "--learner-id")
            if learner_id is None:
                return 2
            await _start_diagnostic(service, learner_id, args.maximum_items)

        if args.diagnostic_status:
            if args.diagnostic_id is None:
                print("error: --diagnostic-status requires --diagnostic-id", file=sys.stderr)
                return 2
            diagnostic_id = _parse_uuid(args.diagnostic_id, "--diagnostic-id")
            if diagnostic_id is None:
                return 2
            await _print_diagnostic_status(unit_of_work_factory, diagnostic_id)

        if args.due_reviews:
            if args.learner_id is None:
                print("error: --due-reviews requires --learner-id", file=sys.stderr)
                return 2
            learner_id = _parse_uuid(args.learner_id, "--learner-id")
            if learner_id is None:
                return 2
            await _print_due_reviews(unit_of_work_factory, learner_id)

        return 0
    except StockResearchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
