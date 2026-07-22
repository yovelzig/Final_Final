"""Unit tests for the learning-repository extension to `SqlAlchemyUnitOfWork`.

Uses a mocked session factory - no real database. The existing market
repositories (tested in `tests/unit/test_unit_of_work.py`) must keep
working unchanged alongside the new learning repositories.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from stock_research_core.infrastructure.database.repositories.attempt_repository import (
    SqlAlchemyAttemptRepository,
)
from stock_research_core.infrastructure.database.repositories.curriculum_repository import (
    SqlAlchemyCurriculumRepository,
)
from stock_research_core.infrastructure.database.repositories.learner_repository import (
    SqlAlchemyLearnerRepository,
)
from stock_research_core.infrastructure.database.repositories.mastery_repository import (
    SqlAlchemyMasteryRepository,
)
from stock_research_core.infrastructure.database.repositories.misconception_repository import (
    SqlAlchemyMisconceptionRepository,
)
from stock_research_core.infrastructure.database.repositories.progress_repository import (
    SqlAlchemyProgressRepository,
)
from stock_research_core.infrastructure.database.repositories.security_repository import (
    SqlAlchemySecurityRepository,
)
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


def _make_session_factory() -> tuple[MagicMock, AsyncMock]:
    session = AsyncMock()
    session_factory = MagicMock(return_value=session)
    return session_factory, session


async def test_entering_builds_all_learning_repositories() -> None:
    session_factory, session = _make_session_factory()
    uow = SqlAlchemyUnitOfWork(session_factory)

    async with uow:
        assert isinstance(uow.learners, SqlAlchemyLearnerRepository)
        assert isinstance(uow.curriculum, SqlAlchemyCurriculumRepository)
        assert isinstance(uow.attempts, SqlAlchemyAttemptRepository)
        assert isinstance(uow.mastery, SqlAlchemyMasteryRepository)
        assert isinstance(uow.progress, SqlAlchemyProgressRepository)
        assert isinstance(uow.misconceptions, SqlAlchemyMisconceptionRepository)
        assert uow.learners._session is session
        assert uow.curriculum._session is session


async def test_existing_market_repositories_still_present() -> None:
    session_factory, _ = _make_session_factory()
    uow = SqlAlchemyUnitOfWork(session_factory)

    async with uow:
        assert isinstance(uow.securities, SqlAlchemySecurityRepository)


async def test_all_repositories_share_the_same_session() -> None:
    session_factory, session = _make_session_factory()
    uow = SqlAlchemyUnitOfWork(session_factory)

    async with uow:
        repos = [
            uow.securities,
            uow.market_bars,
            uow.ingestion_runs,
            uow.tracked_securities,
            uow.learners,
            uow.curriculum,
            uow.attempts,
            uow.mastery,
            uow.progress,
            uow.misconceptions,
        ]
        assert all(repo._session is session for repo in repos)


async def test_commit_and_rollback_still_delegate_to_the_session() -> None:
    session_factory, session = _make_session_factory()
    uow = SqlAlchemyUnitOfWork(session_factory)

    async with uow:
        await uow.commit()
    session.commit.assert_awaited_once()

    uow2 = SqlAlchemyUnitOfWork(session_factory)
    async with uow2:
        await uow2.rollback()
    session.rollback.assert_awaited_once()
