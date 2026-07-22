"""Integration tests for the LangGraph `AsyncPostgresSaver` checkpointer
against the real PostgreSQL test database.

Windows-only note: psycopg's async mode requires
`WindowsSelectorEventLoopPolicy` (the default `ProactorEventLoop`
cannot run it) - set at module level here, deliberately *not* in the
shared `tests/integration/conftest.py` (see that file's Phase 12 note
for why forcing it session-wide destabilizes unrelated
`BaseHTTPMiddleware`-based tests). A no-op on Linux/Docker/CI, where
this whole distinction does not exist.
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from stock_research_core.infrastructure.learning_orchestrator.postgres_checkpointer import (
    build_checkpointer,
    build_checkpointer_pool,
    setup_checkpointer_tables,
    to_psycopg_conninfo,
)

pytestmark = pytest.mark.integration


def test_to_psycopg_conninfo_strips_the_sqlalchemy_driver_suffix() -> None:
    conninfo = to_psycopg_conninfo("postgresql+asyncpg://user:pass@host:5432/db")
    assert conninfo == "postgresql://user:pass@host:5432/db"
    assert "+asyncpg" not in conninfo


async def test_setup_checkpointer_tables_is_idempotent(database_settings) -> None:
    conninfo = to_psycopg_conninfo(database_settings.test_database_url)
    await setup_checkpointer_tables(conninfo)
    await setup_checkpointer_tables(conninfo)  # second call must not raise


async def test_checkpointer_persists_and_restores_state_across_pool_instances(database_settings) -> None:
    """State written through one connection pool must be readable
    through a completely separate pool instance - the checkpoint lives
    in PostgreSQL, not in any in-process cache."""
    conninfo = to_psycopg_conninfo(database_settings.test_database_url)
    await setup_checkpointer_tables(conninfo)

    class _State(TypedDict):
        value: str

    async def _set_value(state: _State) -> dict:
        return {"value": "written"}

    graph_builder = StateGraph(_State)
    graph_builder.add_node("set_value", _set_value)
    graph_builder.add_edge(START, "set_value")
    graph_builder.add_edge("set_value", END)

    thread_id = str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    pool_a = build_checkpointer_pool(conninfo, min_size=1, max_size=2)
    await pool_a.open()
    try:
        graph_a = graph_builder.compile(checkpointer=build_checkpointer(pool_a))
        result = await graph_a.ainvoke({"value": "initial"}, config=config)
        assert result["value"] == "written"
    finally:
        await pool_a.close()

    pool_b = build_checkpointer_pool(conninfo, min_size=1, max_size=2)
    await pool_b.open()
    try:
        graph_b = graph_builder.compile(checkpointer=build_checkpointer(pool_b))
        state = await graph_b.aget_state(config)
        assert state is not None
        assert state.values["value"] == "written"
    finally:
        await pool_b.close()
