"""Shared fixtures for PostgreSQL/TimescaleDB integration tests.

These tests run against the real test database configured by
`TEST_DATABASE_URL` (see `.env.example` / docker-compose's `stock-db`
service, database `stock_research_test`). If that database is not
reachable, every test marked `@pytest.mark.integration` is skipped
cleanly at collection time - no test ever silently passes without
having actually run against PostgreSQL.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import (
    check_database_connection,
    create_database_engine,
    create_session_factory,
)
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

# Phase 12 note: the LangGraph PostgreSQL checkpointer (psycopg async
# mode) requires `WindowsSelectorEventLoopPolicy` on Windows, which is
# NOT set here deliberately - forcing it for the whole integration
# session destabilizes unrelated `BaseHTTPMiddleware`-based API tests
# (observed hang in `/ready`). The checkpointer-specific integration
# tests (`test_langgraph_postgres_checkpointer.py`,
# `test_orchestrator_resume.py`, etc.) set the policy themselves, in
# their own dedicated test session/process - see those files' module
# docstrings. A no-op on Linux/CI either way.

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Children before parents, so a plain (non-cascading) cleanup would also work.
_TABLES_IN_DEPENDENCY_ORDER = [
    "learning_quality_aggregates",
    "quality_evaluation_baselines",
    "quality_metric_results",
    "quality_evaluation_sample_citations",
    "quality_evaluation_sample_retrieved_chunks",
    "quality_evaluation_sample_retrieved_documents",
    "quality_evaluation_sample_results",
    "quality_evaluation_runs",
    "quality_evaluation_case_skills",
    "quality_evaluation_case_reference_chunks",
    "quality_evaluation_case_reference_documents",
    "quality_evaluation_cases",
    "quality_evaluation_suites",
    "learning_orchestrator_action_proposals",
    "learning_orchestrator_events",
    "learning_orchestrator_runs",
    "learning_orchestrator_threads",
    "integration_requests",
    "integration_client_allowed_job_types",
    "integration_clients",
    "background_job_events",
    "background_job_attempts",
    "background_jobs",
    "authentication_audit_events",
    "account_refresh_tokens",
    "user_accounts",
    "tutor_knowledge_gap_skills",
    "tutor_knowledge_gaps",
    "tutor_answer_citations",
    "tutor_answers",
    "tutor_guardrail_decisions",
    "tutor_retrieval_run_chunks",
    "tutor_retrieval_runs",
    "tutor_messages",
    "tutor_conversations",
    "knowledge_ingestion_runs",
    "knowledge_chunk_embeddings",
    "knowledge_chunks",
    "knowledge_document_skills",
    "knowledge_documents",
    "knowledge_sources",
    "portfolio_valuation_runs",
    "portfolio_risk_assessment_skills",
    "portfolio_risk_assessment_feedback_codes",
    "portfolio_risk_assessments",
    "portfolio_position_valuations",
    "portfolio_valuation_snapshots",
    "portfolio_decision_journal_assumptions",
    "portfolio_decision_journal_information_items",
    "portfolio_decision_journal_risk_tags",
    "portfolio_decision_journal_entries",
    "portfolio_holdings",
    "portfolio_transactions",
    "virtual_portfolios",
    "scenario_generation_runs",
    "scenario_submission_feedback_codes",
    "scenario_submissions",
    "scenario_outcomes",
    "scenario_option_rubric_feedback_codes",
    "scenario_option_rubrics",
    "scenario_securities",
    "historical_market_scenario_secondary_skills",
    "historical_market_scenario_primary_skills",
    "historical_market_scenarios",
    "learning_session_activities",
    "adaptive_decision_reasons",
    "adaptive_decision_target_skills",
    "adaptive_decisions",
    "diagnostic_item_skills",
    "diagnostic_assessment_items",
    "diagnostic_assessment_skills",
    "diagnostic_assessments",
    "skill_review_schedules",
    "learning_sessions",
    "exercise_adaptive_profiles",
    "market_data_quality_issues",
    "market_data_ingestion_runs",
    "tracked_securities",
    "market_bars",
    "securities",
    "misconception_evidence_attempts",
    "misconceptions",
    "user_progress",
    "skill_mastery",
    "exercise_answer_ordered_options",
    "exercise_answer_selected_options",
    "exercise_answers",
    "exercise_attempts",
    "exercise_options",
    "exercise_skills",
    "exercises",
    "lesson_secondary_skills",
    "lessons",
    "learning_modules",
    "skill_prerequisites",
    "learning_paths",
    "learner_profiles",
    "financial_skills",
]


def _check_test_database_available() -> tuple[bool, DatabaseSettings]:
    settings = DatabaseSettings()
    if not settings.test_database_url:
        return False, settings
    engine = create_database_engine(settings, database_url=settings.test_database_url)
    try:
        available = asyncio.run(check_database_connection(engine))
    finally:
        asyncio.run(engine.dispose())
    return available, settings


_TEST_DATABASE_AVAILABLE, _SETTINGS = _check_test_database_available()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _TEST_DATABASE_AVAILABLE:
        return
    reason = (
        "PostgreSQL/TimescaleDB test database is not configured or not reachable "
        f"at {_SETTINGS.masked_test_database_url()}. Start it with "
        "'docker compose up -d stock-db' to run integration tests."
    )
    skip_marker = pytest.mark.skip(reason=reason)
    for item in items:
        if item.get_closest_marker("integration") is not None:
            item.add_marker(skip_marker)


def _run_migrations(test_database_url: str) -> None:
    """Apply Alembic migrations to `test_database_url` (idempotent)."""
    alembic_cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))
    previous = os.environ.get("ALEMBIC_DATABASE_URL")
    os.environ["ALEMBIC_DATABASE_URL"] = test_database_url
    try:
        command.upgrade(alembic_cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("ALEMBIC_DATABASE_URL", None)
        else:
            os.environ["ALEMBIC_DATABASE_URL"] = previous


@pytest.fixture(scope="session")
def database_settings() -> DatabaseSettings:
    return _SETTINGS


@pytest.fixture(scope="session", autouse=True)
def _migrated_test_database(database_settings: DatabaseSettings) -> None:
    """Ensure the test database schema is up to date before any test runs.

    Only ever invoked when at least one non-skipped integration test needs
    it, since every integration test is skip-marked when the database is
    unreachable (see `pytest_collection_modifyitems` above).
    """
    assert database_settings.test_database_url is not None
    _run_migrations(database_settings.test_database_url)


@pytest.fixture(scope="session")
def test_engine(database_settings: DatabaseSettings) -> AsyncEngine:
    return create_database_engine(database_settings, database_url=database_settings.test_database_url)


@pytest.fixture(scope="session")
def uow_factory(test_engine: AsyncEngine) -> Callable[[], SqlAlchemyUnitOfWork]:
    session_factory = create_session_factory(test_engine)
    return lambda: SqlAlchemyUnitOfWork(session_factory)


@pytest.fixture(autouse=True)
async def _clean_tables(test_engine: AsyncEngine) -> AsyncIterator[None]:
    """Truncate all Phase 3 tables before each test for isolation."""
    async with test_engine.begin() as connection:
        await connection.execute(
            text(f"TRUNCATE TABLE {', '.join(_TABLES_IN_DEPENDENCY_ORDER)} RESTART IDENTITY CASCADE;")
        )
    yield


# -- Phase 9: FastAPI application fixtures -----------------------------------------------
#
# `api_app`'s own lifespan opens an independent engine/connection pool
# against the same `database_settings.test_database_url` that
# `test_engine` above uses - a separate pool, but the same physical
# database, so `_clean_tables`'s truncation (via `test_engine`) is
# immediately visible through `api_app`'s connections too.


@pytest.fixture(scope="session")
def api_settings():
    from stock_research_core.api.settings import ApiSettings

    return ApiSettings(api_rate_limit_enabled=False)


@pytest.fixture(scope="session")
async def api_app(database_settings: DatabaseSettings, api_settings):
    from stock_research_core.api.app_factory import create_app
    from stock_research_core.infrastructure.ai_tutor.config import EmbeddingSettings, TutorModelSettings
    from stock_research_core.infrastructure.operations.config import OperationsSettings

    # `create_database_engine()` defaults to `settings.database_url` (the
    # dev database) unless overridden - point the app's own engine at the
    # same `test_database_url` the rest of this file's fixtures use.
    assert database_settings.test_database_url is not None
    api_database_settings = database_settings.model_copy(
        update={"database_url": database_settings.test_database_url}
    )

    app = create_app(
        testing=True,
        database_settings=api_database_settings,
        api_settings=api_settings,
        embedding_settings=EmbeddingSettings(embedding_provider="deterministic_fake"),
        tutor_model_settings=TutorModelSettings(tutor_model_provider="extractive"),
        # This general-purpose fixture doesn't provision Redis/a worker -
        # dedicated Phase 11 operations tests build their own `create_app`
        # (or a Redis-backed fixture) when they need those signals.
        operations_settings=OperationsSettings(readiness_require_redis=False, readiness_require_worker=False),
    )
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def api_client(api_app):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def register_account(
    api_client, *, email: str, password: str = "StrongPassword123!", display_name: str = "Test User"
) -> dict:
    """Registers a fresh LEARNER account and returns the full response JSON
    (`account`, `learner`, `tokens`)."""
    response = await api_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": display_name},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def auth_headers(api_client, *, email: str | None = None, **kwargs: object) -> dict[str, str]:
    """Registers a fresh account (unique email if not given) and returns ready-to-use
    `Authorization` headers for it."""
    import uuid

    body = await register_account(
        api_client, email=email or f"user-{uuid.uuid4().hex[:10]}@example.com", **kwargs
    )
    return {"Authorization": f"Bearer {body['tokens']['access_token']}"}


async def promote_role(uow_factory, *, account_id, role: str) -> None:
    """Test-only bypass standing in for the not-yet-built admin-promotion
    flow: `cli/identity_admin.py` can create an ADMIN account directly, but
    there is intentionally no HTTP endpoint that lets any caller change
    their own role. `UserAccountRepositoryPort` has no `update_role`
    primitive (by design - see the CLI's `--create-admin`, which sets the
    role only at account-creation time), so this test-only helper writes
    the role directly through the ORM row.
    """
    from sqlalchemy import update

    from stock_research_core.infrastructure.database.orm.user_account import UserAccountORM

    async with uow_factory() as uow:
        await uow._session.execute(  # noqa: SLF001 - test-only direct write, not a production code path
            update(UserAccountORM).where(UserAccountORM.account_id == account_id).values(role=role)
        )
        await uow.commit()
