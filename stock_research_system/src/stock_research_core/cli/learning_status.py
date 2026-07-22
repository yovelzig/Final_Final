"""CLI for the FinQuest learning platform.

Curriculum status (PowerShell):

    python -m stock_research_core.cli.learning_status --curriculum

Create a learner (defaults to preferred_language="en"):

    python -m stock_research_core.cli.learning_status --create-learner "Amit"

View a learner's dashboard:

    python -m stock_research_core.cli.learning_status --learner-id <UUID>

This module is a composition root: it is the one place outside the
infrastructure layer allowed to import concrete adapters directly.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from stock_research_core.application.exceptions import StockResearchError
from stock_research_core.application.learning.service import LearningService
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from stock_research_core.infrastructure.database.orm.exercise import ExerciseORM
from stock_research_core.infrastructure.database.orm.learning_module import LearningModuleORM
from stock_research_core.infrastructure.database.orm.learning_path import LearningPathORM
from stock_research_core.infrastructure.database.orm.lesson import LessonORM
from stock_research_core.infrastructure.database.orm.skill import FinancialSkillORM
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stock_research_core.cli.learning_status",
        description="Inspect the FinQuest learning platform: curriculum status, learner creation, and dashboards.",
    )
    parser.add_argument(
        "--curriculum", action="store_true", help="Print curriculum content counts"
    )
    parser.add_argument(
        "--create-learner",
        metavar="DISPLAY_NAME",
        default=None,
        help="Create a new learner with this display name (preferred_language defaults to 'en')",
    )
    parser.add_argument(
        "--learner-id", metavar="UUID", default=None, help="Print the dashboard for this learner ID"
    )
    return parser


async def _print_curriculum_status(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        skills = (
            await connection.execute(select(func.count()).select_from(FinancialSkillORM))
        ).scalar_one()
        paths = (
            await connection.execute(select(func.count()).select_from(LearningPathORM))
        ).scalar_one()
        modules = (
            await connection.execute(select(func.count()).select_from(LearningModuleORM))
        ).scalar_one()
        lessons = (
            await connection.execute(select(func.count()).select_from(LessonORM))
        ).scalar_one()
        exercises = (
            await connection.execute(select(func.count()).select_from(ExerciseORM))
        ).scalar_one()

    print("Curriculum status:")
    print(f"  Skills:    {skills}")
    print(f"  Paths:     {paths}")
    print(f"  Modules:   {modules}")
    print(f"  Lessons:   {lessons}")
    print(f"  Exercises: {exercises}")


async def _create_learner(service: LearningService, display_name: str) -> None:
    learner = await service.create_learner(display_name=display_name)
    print("Learner created:")
    print(f"  Learner ID:         {learner.learner_id}")
    print(f"  Display name:       {learner.display_name}")
    print(f"  Preferred language: {learner.preferred_language}")
    print(f"  Experience level:   {learner.financial_experience_level.value}")
    print(f"  Daily goal (min):   {learner.daily_goal_minutes}")


async def _print_learner_dashboard(service: LearningService, learner_id: UUID) -> None:
    dashboard = await service.get_learner_dashboard(learner_id)
    print("Learner dashboard:")
    print(f"  Display name:       {dashboard.learner.display_name}")
    print(f"  Preferred language: {dashboard.learner.preferred_language}")
    print(
        f"  Active path:        {dashboard.active_path.title if dashboard.active_path else 'none'}"
    )
    print(
        f"  Current lesson:     "
        f"{dashboard.current_lesson.title if dashboard.current_lesson else 'none'}"
    )
    print(f"  Completed lessons:  {dashboard.completed_lessons}/{dashboard.total_lessons}")
    print(f"  Current streak:     {dashboard.current_streak_days} day(s)")
    print(f"  Total XP:           {dashboard.total_xp}")
    print(f"  Skills tracked:     {len(dashboard.skill_mastery)}")
    for mastery in dashboard.skill_mastery:
        print(
            f"    - skill {mastery.skill_id}: {mastery.mastery_level.value} "
            f"(score={mastery.mastery_score:.2f})"
        )
    print(f"  Active misconceptions: {len(dashboard.active_misconceptions)}")


async def _run(args: argparse.Namespace) -> int:
    if not (args.curriculum or args.create_learner or args.learner_id):
        print("error: specify --curriculum, --create-learner, or --learner-id", file=sys.stderr)
        return 2

    settings = DatabaseSettings()
    engine = create_database_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        service = LearningService(
            unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(session_factory)
        )

        if args.curriculum:
            await _print_curriculum_status(engine)

        if args.create_learner:
            await _create_learner(service, args.create_learner)

        if args.learner_id:
            try:
                learner_id = UUID(args.learner_id)
            except ValueError:
                print(f"error: '{args.learner_id}' is not a valid UUID", file=sys.stderr)
                return 2
            await _print_learner_dashboard(service, learner_id)

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
