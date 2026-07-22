"""SQLAlchemy repository for `ScenarioOutcome` persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.domain.market_scenarios.models import ScenarioOutcome
from stock_research_core.infrastructure.database.mappers.market_scenario_mappers import (
    scenario_outcome_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.scenario_outcome import ScenarioOutcomeORM


class SqlAlchemyScenarioOutcomeRepository:
    """Persists and queries `ScenarioOutcome` rows. Unique per (scenario,
    calculation_version): re-upserting the same version updates the
    same row in place, so the same stored bars always reproduce the
    same outcome.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, outcome: ScenarioOutcome) -> ScenarioOutcome:
        insert_stmt = pg_insert(ScenarioOutcomeORM).values(
            outcome_id=outcome.outcome_id,
            scenario_id=outcome.scenario_id,
            decision_at=outcome.decision_at,
            reveal_end_at=outcome.reveal_end_at,
            focal_start_close=outcome.focal_start_close,
            focal_end_close=outcome.focal_end_close,
            focal_return=outcome.focal_return,
            maximum_future_upside=outcome.maximum_future_upside,
            maximum_future_drawdown=outcome.maximum_future_drawdown,
            benchmark_return=outcome.benchmark_return,
            excess_return=outcome.excess_return,
            outcome_direction=outcome.outcome_direction.value,
            outcome_summary=outcome.outcome_summary,
            calculation_version=outcome.calculation_version,
        )
        statement = insert_stmt.on_conflict_do_update(
            index_elements=["scenario_id", "calculation_version"],
            set_={
                "decision_at": insert_stmt.excluded.decision_at,
                "reveal_end_at": insert_stmt.excluded.reveal_end_at,
                "focal_start_close": insert_stmt.excluded.focal_start_close,
                "focal_end_close": insert_stmt.excluded.focal_end_close,
                "focal_return": insert_stmt.excluded.focal_return,
                "maximum_future_upside": insert_stmt.excluded.maximum_future_upside,
                "maximum_future_drawdown": insert_stmt.excluded.maximum_future_drawdown,
                "benchmark_return": insert_stmt.excluded.benchmark_return,
                "excess_return": insert_stmt.excluded.excess_return,
                "outcome_direction": insert_stmt.excluded.outcome_direction,
                "outcome_summary": insert_stmt.excluded.outcome_summary,
            },
        ).returning(ScenarioOutcomeORM.outcome_id)
        result = await self._session.execute(statement)
        canonical_id = result.scalar_one()
        await self._session.flush()
        row = await self._session.get(ScenarioOutcomeORM, canonical_id)
        assert row is not None
        return scenario_outcome_orm_to_domain(row)

    async def get(
        self, scenario_id: UUID, calculation_version: str | None = None
    ) -> ScenarioOutcome | None:
        statement = select(ScenarioOutcomeORM).where(ScenarioOutcomeORM.scenario_id == scenario_id)
        if calculation_version is not None:
            statement = statement.where(ScenarioOutcomeORM.calculation_version == calculation_version)
        statement = statement.order_by(ScenarioOutcomeORM.calculated_at.desc()).limit(1)
        result = await self._session.execute(statement)
        row = result.scalar_one_or_none()
        return scenario_outcome_orm_to_domain(row) if row is not None else None
