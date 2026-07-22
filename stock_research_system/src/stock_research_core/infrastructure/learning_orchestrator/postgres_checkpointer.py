"""The official LangGraph PostgreSQL checkpointer (`AsyncPostgresSaver`) -
orchestration runtime state only (graph state snapshots, interrupt
state, resumption, history). The FinQuest-owned, publicly auditable
state (threads/runs/events/actions) is a completely separate concern,
persisted through the normal SQLAlchemy Unit of Work - see
`domain.learning_orchestrator.models` and
`infrastructure.database.repositories.learning_orchestrator_*`.

Nothing in this module connects to PostgreSQL at import time. A
connection pool is only opened when `open_checkpointer_pool()` is
called explicitly (from `api.app_factory`'s `lifespan`, or from the
`learning_orchestrator_admin` CLI's composition root) - never as a
side effect of importing this module or any module that imports it.

We build our own `psycopg_pool.AsyncConnectionPool` and hand it to
`AsyncPostgresSaver(conn=pool)` directly, rather than using
`AsyncPostgresSaver.from_conn_string(...)` (which owns a single
connection, not a pool, and is meant for short-lived scripts) - this
gives the API process explicit control over pool open/close timing,
matching the SQLAlchemy engine's lifecycle in `app_factory.lifespan`.
The connection kwargs (`autocommit=True, prepare_threshold=0,
row_factory=dict_row`) mirror exactly what `from_conn_string` itself
uses internally, per the official implementation.
"""

from __future__ import annotations

import re

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

_SQLALCHEMY_DRIVER_SUFFIX_PATTERN = re.compile(r"^postgresql\+[a-z0-9_]+://")

_POOL_CONNECTION_KWARGS = {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}


def to_psycopg_conninfo(sqlalchemy_database_url: str) -> str:
    """Convert a SQLAlchemy-style URL (`postgresql+asyncpg://...`) to a
    plain `postgresql://...` conninfo string psycopg understands - the
    two libraries are configured from the same `DATABASE_URL`, but each
    needs its own driver-suffix convention."""
    return _SQLALCHEMY_DRIVER_SUFFIX_PATTERN.sub("postgresql://", sqlalchemy_database_url)


def build_checkpointer_pool(conninfo: str, *, min_size: int = 1, max_size: int = 5) -> AsyncConnectionPool:
    """Construct (but do not open) a connection pool. Callers must
    `await pool.open()` before use and `await pool.close()` on shutdown -
    this function never performs I/O itself."""
    return AsyncConnectionPool(
        conninfo, min_size=min_size, max_size=max_size, open=False, kwargs=_POOL_CONNECTION_KWARGS,
    )


def build_checkpointer(pool: AsyncConnectionPool) -> AsyncPostgresSaver:
    """Wrap an already-open pool in the official checkpointer. Does not
    itself run `setup()` - table creation is an explicit, one-time
    administrative step (`learning_orchestrator_admin --setup-checkpointer`),
    never run automatically on every API worker startup."""
    return AsyncPostgresSaver(conn=pool)


async def setup_checkpointer_tables(conninfo: str) -> None:
    """The one-time, idempotent checkpoint-table setup - `AsyncPostgresSaver.setup()`
    uses `CREATE TABLE IF NOT EXISTS` / versioned migrations internally, so
    calling this more than once is always safe. Opens and closes its own
    short-lived pool; never called from `lifespan` or any request path."""
    pool = build_checkpointer_pool(conninfo, min_size=1, max_size=1)
    await pool.open()
    try:
        checkpointer = build_checkpointer(pool)
        await checkpointer.setup()
    finally:
        await pool.close()
