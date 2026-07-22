"""Seed the fixed, deterministic learner reserved for Phase 13 quality-
evaluation fixtures (`TutorGroundedCaseExecutor.EVALUATION_FIXTURE_
LEARNER_ID`).

Idempotent: the learner id is a stable `uuid5` derivation, so re-running
this script is always a safe no-op once the row exists. This learner is
never used for any real learner activity - every evaluation
conversation created under it is closed immediately after the case that
opened it finishes (spec section 16: evaluation must never mutate real
learner state or linger in a real learner's history).

Usage (PowerShell):

    python scripts/seed_quality_evaluation_fixtures.py
"""

from __future__ import annotations

import asyncio

from stock_research_core.domain.learning.models import LearnerProfile
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import create_database_engine, create_session_factory
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from stock_research_core.infrastructure.quality_evaluation.tutor_case_executor import EVALUATION_FIXTURE_LEARNER_ID


async def seed() -> None:
    settings = DatabaseSettings()
    engine = create_database_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        uow = SqlAlchemyUnitOfWork(session_factory)

        async with uow:
            existing = await uow.learners.get(EVALUATION_FIXTURE_LEARNER_ID)
            if existing is not None:
                print(f"Evaluation fixture learner '{EVALUATION_FIXTURE_LEARNER_ID}' already exists.")
                return
            await uow.learners.create(
                LearnerProfile(
                    learner_id=EVALUATION_FIXTURE_LEARNER_ID,
                    display_name="FinQuest Quality Evaluation Fixture (do not use for real learning activity)",
                )
            )
            await uow.commit()
        print(f"Seeded evaluation fixture learner '{EVALUATION_FIXTURE_LEARNER_ID}'.")
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
