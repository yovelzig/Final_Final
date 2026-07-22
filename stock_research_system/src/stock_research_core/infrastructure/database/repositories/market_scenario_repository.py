"""SQLAlchemy repository for `HistoricalMarketScenario` persistence.

`focal_security_id`/`benchmark_security_id` and the primary/secondary
skill lists are stored in association tables
(`scenario_securities`, `historical_market_scenario_primary_skills`,
`historical_market_scenario_secondary_skills`) and replaced wholesale
on each upsert - the same idempotent pattern already used by
`SqlAlchemyCurriculumRepository` for lesson/exercise associations.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import DatabaseMappingError, PersistenceError
from stock_research_core.domain.market_scenarios.enums import (
    MarketScenarioStatus,
    MarketScenarioType,
    ScenarioSecurityRole,
)
from stock_research_core.domain.market_scenarios.models import HistoricalMarketScenario
from stock_research_core.infrastructure.database.mappers.market_scenario_mappers import (
    historical_market_scenario_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.historical_market_scenario import (
    HistoricalMarketScenarioORM,
    HistoricalMarketScenarioPrimarySkillORM,
    HistoricalMarketScenarioSecondarySkillORM,
)
from stock_research_core.infrastructure.database.orm.scenario_security import ScenarioSecurityORM


class SqlAlchemyMarketScenarioRepository:
    """Persists and queries `HistoricalMarketScenario` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, scenario: HistoricalMarketScenario) -> HistoricalMarketScenario:
        insert_stmt = pg_insert(HistoricalMarketScenarioORM).values(
            scenario_id=scenario.scenario_id,
            exercise_id=scenario.exercise_id,
            code=scenario.code,
            title=scenario.title,
            description=scenario.description,
            scenario_type=scenario.scenario_type.value,
            status=scenario.status.value,
            observation_start_at=scenario.observation_start_at,
            decision_at=scenario.decision_at,
            reveal_end_at=scenario.reveal_end_at,
            interval=scenario.interval,
            source_name=scenario.source_name,
            prompt=scenario.prompt,
            learner_instructions=scenario.learner_instructions,
            learning_objectives=list(scenario.learning_objectives),
            minimum_observation_bars=scenario.minimum_observation_bars,
            minimum_reveal_bars=scenario.minimum_reveal_bars,
            scenario_version=scenario.scenario_version,
        )
        statement = insert_stmt.on_conflict_do_update(
            index_elements=["scenario_id"],
            set_={
                "exercise_id": insert_stmt.excluded.exercise_id,
                "code": insert_stmt.excluded.code,
                "title": insert_stmt.excluded.title,
                "description": insert_stmt.excluded.description,
                "scenario_type": insert_stmt.excluded.scenario_type,
                "status": insert_stmt.excluded.status,
                "observation_start_at": insert_stmt.excluded.observation_start_at,
                "decision_at": insert_stmt.excluded.decision_at,
                "reveal_end_at": insert_stmt.excluded.reveal_end_at,
                "interval": insert_stmt.excluded.interval,
                "source_name": insert_stmt.excluded.source_name,
                "prompt": insert_stmt.excluded.prompt,
                "learner_instructions": insert_stmt.excluded.learner_instructions,
                "learning_objectives": insert_stmt.excluded.learning_objectives,
                "minimum_observation_bars": insert_stmt.excluded.minimum_observation_bars,
                "minimum_reveal_bars": insert_stmt.excluded.minimum_reveal_bars,
                "scenario_version": insert_stmt.excluded.scenario_version,
                "updated_at": func.now(),
            },
        )
        await self._session.execute(statement)

        await self._session.execute(
            delete(ScenarioSecurityORM).where(ScenarioSecurityORM.scenario_id == scenario.scenario_id)
        )
        self._session.add(
            ScenarioSecurityORM(
                scenario_security_id=uuid4(),
                scenario_id=scenario.scenario_id,
                security_id=scenario.focal_security_id,
                role=ScenarioSecurityRole.FOCAL.value,
            )
        )
        if scenario.benchmark_security_id is not None:
            self._session.add(
                ScenarioSecurityORM(
                    scenario_security_id=uuid4(),
                    scenario_id=scenario.scenario_id,
                    security_id=scenario.benchmark_security_id,
                    role=ScenarioSecurityRole.BENCHMARK.value,
                )
            )

        await self._session.execute(
            delete(HistoricalMarketScenarioPrimarySkillORM).where(
                HistoricalMarketScenarioPrimarySkillORM.scenario_id == scenario.scenario_id
            )
        )
        for skill_id in scenario.primary_skill_ids:
            self._session.add(
                HistoricalMarketScenarioPrimarySkillORM(
                    scenario_id=scenario.scenario_id, skill_id=skill_id
                )
            )

        await self._session.execute(
            delete(HistoricalMarketScenarioSecondarySkillORM).where(
                HistoricalMarketScenarioSecondarySkillORM.scenario_id == scenario.scenario_id
            )
        )
        for skill_id in scenario.secondary_skill_ids:
            self._session.add(
                HistoricalMarketScenarioSecondarySkillORM(
                    scenario_id=scenario.scenario_id, skill_id=skill_id
                )
            )
        await self._session.flush()

        row = await self._session.get(HistoricalMarketScenarioORM, scenario.scenario_id)
        assert row is not None
        return await self._to_domain(row)

    async def get(self, scenario_id: UUID) -> HistoricalMarketScenario | None:
        row = await self._session.get(HistoricalMarketScenarioORM, scenario_id)
        return await self._to_domain(row) if row is not None else None

    async def get_by_code(self, code: str) -> HistoricalMarketScenario | None:
        result = await self._session.execute(
            select(HistoricalMarketScenarioORM).where(HistoricalMarketScenarioORM.code == code)
        )
        row = result.scalar_one_or_none()
        return await self._to_domain(row) if row is not None else None

    async def get_by_exercise_id(self, exercise_id: UUID) -> HistoricalMarketScenario | None:
        result = await self._session.execute(
            select(HistoricalMarketScenarioORM).where(
                HistoricalMarketScenarioORM.exercise_id == exercise_id
            )
        )
        row = result.scalar_one_or_none()
        return await self._to_domain(row) if row is not None else None

    async def list_published(
        self,
        skill_id: UUID | None = None,
        scenario_type: MarketScenarioType | None = None,
    ) -> list[HistoricalMarketScenario]:
        statement = select(HistoricalMarketScenarioORM).where(
            HistoricalMarketScenarioORM.status == MarketScenarioStatus.PUBLISHED.value
        )
        if scenario_type is not None:
            statement = statement.where(HistoricalMarketScenarioORM.scenario_type == scenario_type.value)
        if skill_id is not None:
            statement = statement.where(
                HistoricalMarketScenarioORM.scenario_id.in_(
                    select(HistoricalMarketScenarioPrimarySkillORM.scenario_id).where(
                        HistoricalMarketScenarioPrimarySkillORM.skill_id == skill_id
                    )
                )
            )
        statement = statement.order_by(HistoricalMarketScenarioORM.code.asc())
        result = await self._session.execute(statement)
        rows = result.scalars().all()
        return [await self._to_domain(row) for row in rows]

    async def set_status(
        self, scenario_id: UUID, status: MarketScenarioStatus
    ) -> HistoricalMarketScenario:
        row = await self._session.get(HistoricalMarketScenarioORM, scenario_id)
        if row is None:
            raise PersistenceError(f"No scenario found with id '{scenario_id}'.")
        row.status = status.value
        await self._session.flush()
        # `updated_at` has a client-side `onupdate=func.now()` default, so
        # after flush() it is marked expired rather than populated -
        # `refresh()` reloads it in an async-safe way before `_to_domain`
        # (a plain synchronous attribute access) touches it.
        await self._session.refresh(row)
        return await self._to_domain(row)

    async def _to_domain(self, row: HistoricalMarketScenarioORM) -> HistoricalMarketScenario:
        security_result = await self._session.execute(
            select(ScenarioSecurityORM.security_id, ScenarioSecurityORM.role).where(
                ScenarioSecurityORM.scenario_id == row.scenario_id
            )
        )
        focal_security_id: UUID | None = None
        benchmark_security_id: UUID | None = None
        for security_id, role in security_result.all():
            if role == ScenarioSecurityRole.FOCAL.value:
                focal_security_id = security_id
            elif role == ScenarioSecurityRole.BENCHMARK.value:
                benchmark_security_id = security_id
        if focal_security_id is None:
            raise DatabaseMappingError(f"Scenario '{row.scenario_id}' has no FOCAL security row.")

        primary_result = await self._session.execute(
            select(HistoricalMarketScenarioPrimarySkillORM.skill_id).where(
                HistoricalMarketScenarioPrimarySkillORM.scenario_id == row.scenario_id
            )
        )
        secondary_result = await self._session.execute(
            select(HistoricalMarketScenarioSecondarySkillORM.skill_id).where(
                HistoricalMarketScenarioSecondarySkillORM.scenario_id == row.scenario_id
            )
        )
        return historical_market_scenario_orm_to_domain(
            row,
            focal_security_id=focal_security_id,
            benchmark_security_id=benchmark_security_id,
            primary_skill_ids=list(primary_result.scalars().all()),
            secondary_skill_ids=list(secondary_result.scalars().all()),
        )
