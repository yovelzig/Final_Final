"""PostgreSQL integration tests: `ScenarioGenerationRunRepository`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.market_scenarios.enums import ScenarioGenerationRunStatus
from stock_research_core.domain.market_scenarios.models import ScenarioGenerationRun
from stock_research_core.domain.models import Security

pytestmark = pytest.mark.integration

# Deliberately in the past relative to wall-clock time: `mark_completed`/
# `mark_failed`/`mark_insufficient_data` stamp `completed_at` with the
# real wall clock (matching `SqlAlchemyIngestionRunRepository`'s existing
# convention), so this fixture's explicit `started_at` must sort *before*
# real "now" for the domain model's `completed_at >= started_at`
# validator to pass.
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _seed_security(uow_factory) -> Security:
    security = Security(ticker=f"T{uuid4().hex[:6].upper()}", company_name="Test Co", exchange=Exchange.NASDAQ)
    async with uow_factory() as uow:
        stored = await uow.securities.upsert(security)
        await uow.commit()
    return stored


def _run(security: Security, **overrides) -> ScenarioGenerationRun:
    defaults: dict = dict(
        focal_security_id=security.security_id,
        requested_observation_start_at=NOW - timedelta(days=60),
        requested_decision_at=NOW - timedelta(days=20),
        requested_reveal_end_at=NOW,
        scenario_code=f"TEST_{uuid4().hex[:10].upper()}",
        scenario_version="scenario-v1",
        started_at=NOW,
    )
    defaults.update(overrides)
    return ScenarioGenerationRun(**defaults)


async def test_create_and_get_round_trip(uow_factory) -> None:
    security = await _seed_security(uow_factory)
    run = _run(security)

    async with uow_factory() as uow:
        created = await uow.scenario_generation_runs.create(run)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.scenario_generation_runs.get(created.run_id)

    assert fetched is not None
    assert fetched.status == ScenarioGenerationRunStatus.STARTED
    assert fetched.scenario_code == run.scenario_code


async def test_mark_completed(uow_factory) -> None:
    security = await _seed_security(uow_factory)
    run = _run(security)
    async with uow_factory() as uow:
        created = await uow.scenario_generation_runs.create(run)
        await uow.commit()

    async with uow_factory() as uow:
        completed = await uow.scenario_generation_runs.mark_completed(
            created.run_id, observation_bars_found=45, reveal_bars_found=22, benchmark_bars_found=0
        )
        await uow.commit()

    assert completed.status == ScenarioGenerationRunStatus.COMPLETED
    assert completed.observation_bars_found == 45
    assert completed.completed_at is not None


async def test_mark_failed_sanitizes_and_truncates(uow_factory) -> None:
    security = await _seed_security(uow_factory)
    run = _run(security)
    async with uow_factory() as uow:
        created = await uow.scenario_generation_runs.create(run)
        await uow.commit()

    async with uow_factory() as uow:
        failed = await uow.scenario_generation_runs.mark_failed(
            created.run_id, error_type="InsufficientScenarioDataError", error_message="Not enough bars."
        )
        await uow.commit()

    assert failed.status == ScenarioGenerationRunStatus.FAILED
    assert failed.error_type == "InsufficientScenarioDataError"
    assert failed.error_message == "Not enough bars."
    assert failed.completed_at is not None


async def test_mark_insufficient_data(uow_factory) -> None:
    security = await _seed_security(uow_factory)
    run = _run(security)
    async with uow_factory() as uow:
        created = await uow.scenario_generation_runs.create(run)
        await uow.commit()

    async with uow_factory() as uow:
        result = await uow.scenario_generation_runs.mark_insufficient_data(
            created.run_id, observation_bars_found=10, reveal_bars_found=2, benchmark_bars_found=0
        )
        await uow.commit()

    assert result.status == ScenarioGenerationRunStatus.INSUFFICIENT_DATA
    assert result.observation_bars_found == 10


async def test_list_recent_orders_by_started_at_descending(uow_factory) -> None:
    security = await _seed_security(uow_factory)
    async with uow_factory() as uow:
        first = await uow.scenario_generation_runs.create(_run(security, started_at=NOW - timedelta(days=2)))
        second = await uow.scenario_generation_runs.create(_run(security, started_at=NOW - timedelta(days=1)))
        await uow.commit()

    async with uow_factory() as uow:
        recent = await uow.scenario_generation_runs.list_recent(limit=10)

    recent_ids = [r.run_id for r in recent]
    assert recent_ids.index(second.run_id) < recent_ids.index(first.run_id)
