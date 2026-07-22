"""SQLAlchemy repository for `ScenarioGenerationRun` audit-record persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.market_scenarios.enums import ScenarioGenerationRunStatus
from stock_research_core.domain.market_scenarios.models import ScenarioGenerationRun
from stock_research_core.infrastructure.database.mappers.market_scenario_mappers import (
    scenario_generation_run_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.scenario_generation_run import (
    ScenarioGenerationRunORM,
)

_ERROR_TYPE_MAX_LENGTH = 200
_ERROR_MESSAGE_MAX_LENGTH = 2000


class SqlAlchemyScenarioGenerationRunRepository:
    """Creates and updates `ScenarioGenerationRun` audit records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, run: ScenarioGenerationRun) -> ScenarioGenerationRun:
        row = ScenarioGenerationRunORM(
            run_id=run.run_id,
            status=run.status.value,
            focal_security_id=run.focal_security_id,
            benchmark_security_id=run.benchmark_security_id,
            requested_observation_start_at=run.requested_observation_start_at,
            requested_decision_at=run.requested_decision_at,
            requested_reveal_end_at=run.requested_reveal_end_at,
            scenario_code=run.scenario_code,
            scenario_version=run.scenario_version,
            observation_bars_found=run.observation_bars_found,
            reveal_bars_found=run.reveal_bars_found,
            benchmark_bars_found=run.benchmark_bars_found,
            started_at=run.started_at,
            completed_at=run.completed_at,
            error_type=run.error_type,
            error_message=run.error_message,
        )
        self._session.add(row)
        await self._session.flush()
        return scenario_generation_run_orm_to_domain(row)

    async def mark_completed(
        self,
        run_id: UUID,
        *,
        observation_bars_found: int,
        reveal_bars_found: int,
        benchmark_bars_found: int,
    ) -> ScenarioGenerationRun:
        row = await self._get_or_raise(run_id)
        row.status = ScenarioGenerationRunStatus.COMPLETED.value
        row.observation_bars_found = observation_bars_found
        row.reveal_bars_found = reveal_bars_found
        row.benchmark_bars_found = benchmark_bars_found
        row.completed_at = datetime.now(timezone.utc)
        await self._session.flush()
        return scenario_generation_run_orm_to_domain(row)

    async def mark_failed(
        self, run_id: UUID, *, error_type: str, error_message: str
    ) -> ScenarioGenerationRun:
        row = await self._get_or_raise(run_id)
        row.status = ScenarioGenerationRunStatus.FAILED.value
        row.error_type = error_type[:_ERROR_TYPE_MAX_LENGTH]
        row.error_message = error_message[:_ERROR_MESSAGE_MAX_LENGTH]
        row.completed_at = datetime.now(timezone.utc)
        await self._session.flush()
        return scenario_generation_run_orm_to_domain(row)

    async def mark_insufficient_data(
        self,
        run_id: UUID,
        *,
        observation_bars_found: int,
        reveal_bars_found: int,
        benchmark_bars_found: int,
    ) -> ScenarioGenerationRun:
        row = await self._get_or_raise(run_id)
        row.status = ScenarioGenerationRunStatus.INSUFFICIENT_DATA.value
        row.observation_bars_found = observation_bars_found
        row.reveal_bars_found = reveal_bars_found
        row.benchmark_bars_found = benchmark_bars_found
        row.completed_at = datetime.now(timezone.utc)
        await self._session.flush()
        return scenario_generation_run_orm_to_domain(row)

    async def get(self, run_id: UUID) -> ScenarioGenerationRun | None:
        row = await self._session.get(ScenarioGenerationRunORM, run_id)
        return scenario_generation_run_orm_to_domain(row) if row is not None else None

    async def list_recent(self, limit: int = 10) -> list[ScenarioGenerationRun]:
        statement = (
            select(ScenarioGenerationRunORM).order_by(ScenarioGenerationRunORM.started_at.desc()).limit(limit)
        )
        result = await self._session.execute(statement)
        return [scenario_generation_run_orm_to_domain(row) for row in result.scalars().all()]

    async def _get_or_raise(self, run_id: UUID) -> ScenarioGenerationRunORM:
        row = await self._session.get(ScenarioGenerationRunORM, run_id)
        if row is None:
            raise PersistenceError(f"No scenario generation run found with id '{run_id}'.")
        return row
