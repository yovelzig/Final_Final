"""Unit tests for `SqlAlchemyUnitOfWork` using a mocked session factory.

No real database is used: `session_factory` returns an `AsyncMock`
standing in for an `AsyncSession`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from stock_research_core.infrastructure.database.repositories.security_repository import (
    SqlAlchemySecurityRepository,
)
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


def _make_session_factory() -> tuple[MagicMock, AsyncMock]:
    session = AsyncMock()
    session_factory = MagicMock(return_value=session)
    return session_factory, session


async def test_repositories_are_unavailable_before_entering() -> None:
    session_factory, _ = _make_session_factory()
    uow = SqlAlchemyUnitOfWork(session_factory)

    with pytest.raises(AttributeError):
        _ = uow.securities


async def test_entering_builds_repositories_bound_to_the_session() -> None:
    session_factory, session = _make_session_factory()
    uow = SqlAlchemyUnitOfWork(session_factory)

    async with uow as entered:
        assert entered is uow
        assert isinstance(uow.securities, SqlAlchemySecurityRepository)
        assert uow.securities._session is session


async def test_commit_delegates_to_the_session() -> None:
    session_factory, session = _make_session_factory()
    uow = SqlAlchemyUnitOfWork(session_factory)

    async with uow:
        await uow.commit()

    session.commit.assert_awaited_once()


async def test_exit_without_commit_does_not_commit_but_closes() -> None:
    session_factory, session = _make_session_factory()
    uow = SqlAlchemyUnitOfWork(session_factory)

    async with uow:
        pass

    session.commit.assert_not_awaited()
    session.close.assert_awaited_once()


async def test_exception_inside_the_block_triggers_rollback_and_close() -> None:
    session_factory, session = _make_session_factory()
    uow = SqlAlchemyUnitOfWork(session_factory)

    with pytest.raises(RuntimeError):
        async with uow:
            raise RuntimeError("boom")

    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()


async def test_rollback_delegates_to_the_session() -> None:
    session_factory, session = _make_session_factory()
    uow = SqlAlchemyUnitOfWork(session_factory)

    async with uow:
        await uow.rollback()

    session.rollback.assert_awaited_once()
