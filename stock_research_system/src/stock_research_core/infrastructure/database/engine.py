"""Async SQLAlchemy engine and session-factory creation.

Nothing in this module runs at import time. Callers (the CLI, the
Unit of Work, test fixtures) decide when an engine is created and are
responsible for disposing of it.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from stock_research_core.infrastructure.database.config import DatabaseSettings


def create_database_engine(settings: DatabaseSettings, *, database_url: str | None = None) -> AsyncEngine:
    """Create a new async engine from `settings` (or an explicit override URL)."""
    return create_async_engine(
        database_url or settings.database_url,
        echo=settings.database_echo,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to `engine`.

    `expire_on_commit=False` so domain objects mapped from ORM rows
    remain usable after the Unit of Work commits.
    """
    return async_sessionmaker(bind=engine, expire_on_commit=False)


async def check_database_connection(engine: AsyncEngine) -> bool:
    """Return True if a trivial query succeeds against `engine`."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - connectivity checks must never raise
        return False
