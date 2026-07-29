"""Focused integration tests for migration 0013 (Phase G2D2/H1 correction
pass): `trusted_account_id` on `learning_orchestrator_runs` must be safe
against a production table that already has rows.

Covers exactly the scenarios the correction pass requires and nothing
else (no unrelated migration is exercised here):

- upgrade from 0012 with an empty table
- upgrade from 0012 with existing Coach rows, authoritatively backfilled
  through `user_accounts.learner_id`
- a legacy row whose learner has no linked account stays nullable and
  is never deleted, never given an invented/copied value
- downgrade back to 0012
- upgrade again

Each test runs its own downgrade-then-upgrade sequence against the real
`TEST_DATABASE_URL` (never SQLite/a fake - Alembic's Postgres-specific
`postgresql.UUID`/partial-index DDL would not run against one) and always
ends back at `head` (0013 is currently head), so this file is safe to run
either in isolation or alongside the rest of the integration suite:

    pytest tests/integration/test_migration_0013_coach_research_correlation.py -m integration
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PREVIOUS_REVISION = "0012_live_research_domain"
_TARGET_REVISION = "0013_coach_research_correlation"


def _alembic_config(database_url: str) -> Config:
    alembic_cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))
    os.environ["ALEMBIC_DATABASE_URL"] = database_url
    return alembic_cfg


def _downgrade_to_0012(database_url: str) -> None:
    command.downgrade(_alembic_config(database_url), _PREVIOUS_REVISION)


def _upgrade_to_0013(database_url: str) -> None:
    command.upgrade(_alembic_config(database_url), _TARGET_REVISION)


async def _insert_learner(engine: AsyncEngine, learner_id) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO learner_profiles "
                "(learner_id, display_name, preferred_language, financial_experience_level, "
                "daily_goal_minutes, active) "
                "VALUES (:id, 'Test Learner', 'en', 'BEGINNER', 10, true)"
            ),
            {"id": learner_id},
        )


async def _insert_account(engine: AsyncEngine, *, account_id, learner_id, email: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO user_accounts "
                "(account_id, email, normalized_email, display_name, password_hash, learner_id, role, status) "
                "VALUES (:account_id, :email, :email, 'Test', 'x', :learner_id, 'LEARNER', 'ACTIVE')"
            ),
            {"account_id": account_id, "email": email, "learner_id": learner_id},
        )


async def _insert_thread(engine: AsyncEngine, *, thread_id, learner_id) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO learning_orchestrator_threads "
                "(thread_id, learner_id, status, title, current_context_type, graph_name, graph_version) "
                "VALUES (:thread_id, :learner_id, 'ACTIVE', 'Thread', 'GENERAL_EDUCATION', "
                "'finquest-learning-coach', 'learning-coach-graph-v1')"
            ),
            {"thread_id": thread_id, "learner_id": learner_id},
        )


async def _insert_legacy_run(engine: AsyncEngine, *, run_id, thread_id, learner_id) -> None:
    """Inserts a `learning_orchestrator_runs` row using only the pre-0013
    (0010-era) columns - simulates a production row that already existed
    before this migration ever ran, with no knowledge of
    `trusted_account_id`."""
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO learning_orchestrator_runs "
                "(run_id, thread_id, learner_id, status, idempotency_key, correlation_id, graph_version) "
                "VALUES (:run_id, :thread_id, :learner_id, 'SUCCEEDED', :idempotency_key, :correlation_id, "
                "'learning-coach-graph-v1')"
            ),
            {
                "run_id": run_id, "thread_id": thread_id, "learner_id": learner_id,
                "idempotency_key": f"legacy:{run_id}", "correlation_id": str(uuid4()),
            },
        )


async def _column_nullable(engine: AsyncEngine, *, table: str, column: str) -> bool | None:
    """`None` means the column does not exist (e.g. after a downgrade)."""
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": table, "column": column},
        )
        row = result.first()
        return None if row is None else row[0] == "YES"


async def _trusted_account_id(engine: AsyncEngine, *, run_id):
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT trusted_account_id FROM learning_orchestrator_runs WHERE run_id = :run_id"),
            {"run_id": run_id},
        )
        return result.scalar_one()


async def test_upgrade_from_0012_with_empty_table_applies_not_null(
    database_settings, test_engine: AsyncEngine
) -> None:
    database_url = database_settings.test_database_url
    assert database_url is not None
    await asyncio.to_thread(_downgrade_to_0012, database_url)
    try:
        await asyncio.to_thread(_upgrade_to_0013, database_url)
        # No rows existed to backfill, so it is safe to enforce NOT NULL
        # going forward - even the empty-table case must not stay
        # permanently nullable.
        assert await _column_nullable(test_engine, table="learning_orchestrator_runs", column="trusted_account_id") is False
    finally:
        await asyncio.to_thread(_upgrade_to_0013, database_url)  # already at head if the try body succeeded; idempotent no-op


async def test_upgrade_from_0012_with_existing_rows_backfills_authoritatively(
    database_settings, test_engine: AsyncEngine
) -> None:
    database_url = database_settings.test_database_url
    assert database_url is not None
    await asyncio.to_thread(_downgrade_to_0012, database_url)
    try:
        learner_id, account_id, thread_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()
        await _insert_learner(test_engine, learner_id)
        await _insert_account(test_engine, account_id=account_id, learner_id=learner_id, email="learner@example.com")
        await _insert_thread(test_engine, thread_id=thread_id, learner_id=learner_id)
        await _insert_legacy_run(test_engine, run_id=run_id, thread_id=thread_id, learner_id=learner_id)

        await asyncio.to_thread(_upgrade_to_0013, database_url)

        # Backfilled through user_accounts.learner_id - never copied
        # from learner_id, never invented.
        assert await _trusted_account_id(test_engine, run_id=run_id) == account_id
        assert await _trusted_account_id(test_engine, run_id=run_id) != learner_id
        # Every row resolved, so NOT NULL is safe to enforce.
        assert await _column_nullable(test_engine, table="learning_orchestrator_runs", column="trusted_account_id") is False
    finally:
        await asyncio.to_thread(_upgrade_to_0013, database_url)


async def test_unresolved_legacy_row_stays_nullable_and_is_never_deleted(
    database_settings, test_engine: AsyncEngine
) -> None:
    database_url = database_settings.test_database_url
    assert database_url is not None
    await asyncio.to_thread(_downgrade_to_0012, database_url)
    try:
        # A learner with no linked user_accounts row - cannot be
        # resolved authoritatively.
        learner_id, thread_id, run_id = uuid4(), uuid4(), uuid4()
        await _insert_learner(test_engine, learner_id)
        await _insert_thread(test_engine, thread_id=thread_id, learner_id=learner_id)
        await _insert_legacy_run(test_engine, run_id=run_id, thread_id=thread_id, learner_id=learner_id)

        await asyncio.to_thread(_upgrade_to_0013, database_url)

        assert await _trusted_account_id(test_engine, run_id=run_id) is None
        # Column stays nullable - at least one row could not be resolved.
        assert await _column_nullable(test_engine, table="learning_orchestrator_runs", column="trusted_account_id") is True

        # Never deleted.
        async with test_engine.connect() as connection:
            result = await connection.execute(
                text("SELECT status FROM learning_orchestrator_runs WHERE run_id = :run_id"), {"run_id": run_id}
            )
            assert result.scalar_one() == "SUCCEEDED"
    finally:
        await asyncio.to_thread(_upgrade_to_0013, database_url)


async def test_downgrade_back_to_0012_drops_the_column_without_deleting_rows(
    database_settings, test_engine: AsyncEngine
) -> None:
    database_url = database_settings.test_database_url
    assert database_url is not None
    await asyncio.to_thread(_upgrade_to_0013, database_url)  # ensure starting at head

    learner_id, account_id, thread_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()
    await _insert_learner(test_engine, learner_id)
    await _insert_account(test_engine, account_id=account_id, learner_id=learner_id, email="downgrade@example.com")
    await _insert_thread(test_engine, thread_id=thread_id, learner_id=learner_id)
    await _insert_legacy_run(test_engine, run_id=run_id, thread_id=thread_id, learner_id=learner_id)

    try:
        await asyncio.to_thread(_downgrade_to_0012, database_url)

        assert await _column_nullable(test_engine, table="learning_orchestrator_runs", column="trusted_account_id") is None

        async with test_engine.connect() as connection:
            result = await connection.execute(
                text("SELECT status FROM learning_orchestrator_runs WHERE run_id = :run_id"), {"run_id": run_id}
            )
            assert result.scalar_one() == "SUCCEEDED"  # row survived the downgrade intact
    finally:
        await asyncio.to_thread(_upgrade_to_0013, database_url)


async def test_upgrade_again_after_downgrade_is_safe(database_settings, test_engine: AsyncEngine) -> None:
    database_url = database_settings.test_database_url
    assert database_url is not None
    await asyncio.to_thread(_downgrade_to_0012, database_url)
    await asyncio.to_thread(_upgrade_to_0013, database_url)
    await asyncio.to_thread(_downgrade_to_0012, database_url)

    await asyncio.to_thread(_upgrade_to_0013, database_url)  # upgrade again

    assert await _column_nullable(test_engine, table="learning_orchestrator_runs", column="trusted_account_id") is False
