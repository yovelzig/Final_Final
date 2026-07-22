"""SQLAlchemy repository for `ScenarioOptionRubric` persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.domain.market_scenarios.models import ScenarioOptionRubric
from stock_research_core.infrastructure.database.mappers.market_scenario_mappers import (
    scenario_option_rubric_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.scenario_option_rubric import (
    ScenarioOptionRubricFeedbackCodeORM,
    ScenarioOptionRubricORM,
)


class SqlAlchemyScenarioRubricRepository:
    """Persists and queries `ScenarioOptionRubric` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_many(self, rubrics: list[ScenarioOptionRubric]) -> int:
        if not rubrics:
            return 0

        values = [
            {
                "rubric_id": rubric.rubric_id,
                "scenario_id": rubric.scenario_id,
                "exercise_option_id": rubric.exercise_option_id,
                "decision_quality_score": rubric.decision_quality_score,
                "risk_awareness_score": rubric.risk_awareness_score,
                "benchmark_awareness_score": rubric.benchmark_awareness_score,
                "horizon_alignment_score": rubric.horizon_alignment_score,
                "information_sufficiency_score": rubric.information_sufficiency_score,
                "uncertainty_awareness_score": rubric.uncertainty_awareness_score,
                "expected_direction": rubric.expected_direction.value,
                "positive_feedback": rubric.positive_feedback,
                "improvement_feedback": rubric.improvement_feedback,
                "rubric_version": rubric.rubric_version,
            }
            for rubric in rubrics
        ]
        insert_stmt = pg_insert(ScenarioOptionRubricORM).values(values)
        statement = insert_stmt.on_conflict_do_update(
            # `rubric_id` (the actual primary key) is deliberately absent
            # from `set_` - the conflict target is the unique
            # (scenario_id, exercise_option_id, rubric_version)
            # constraint, not the PK, so re-upserting must keep the
            # existing row's `rubric_id` stable rather than reassigning
            # it out from under its own `scenario_option_rubric_feedback_codes`
            # foreign-key references.
            index_elements=["scenario_id", "exercise_option_id", "rubric_version"],
            set_={
                "decision_quality_score": insert_stmt.excluded.decision_quality_score,
                "risk_awareness_score": insert_stmt.excluded.risk_awareness_score,
                "benchmark_awareness_score": insert_stmt.excluded.benchmark_awareness_score,
                "horizon_alignment_score": insert_stmt.excluded.horizon_alignment_score,
                "information_sufficiency_score": insert_stmt.excluded.information_sufficiency_score,
                "uncertainty_awareness_score": insert_stmt.excluded.uncertainty_awareness_score,
                "expected_direction": insert_stmt.excluded.expected_direction,
                "positive_feedback": insert_stmt.excluded.positive_feedback,
                "improvement_feedback": insert_stmt.excluded.improvement_feedback,
                "updated_at": func.now(),
            },
        )
        await self._session.execute(statement)
        await self._session.flush()

        for rubric in rubrics:
            row = await self._get_row(rubric.scenario_id, rubric.exercise_option_id, rubric.rubric_version)
            assert row is not None
            await self._session.execute(
                delete(ScenarioOptionRubricFeedbackCodeORM).where(
                    ScenarioOptionRubricFeedbackCodeORM.rubric_id == row.rubric_id
                )
            )
            for code in rubric.feedback_codes:
                self._session.add(
                    ScenarioOptionRubricFeedbackCodeORM(rubric_id=row.rubric_id, feedback_code=code.value)
                )
        await self._session.flush()
        return len(rubrics)

    async def get_for_option(
        self, scenario_id: UUID, exercise_option_id: UUID
    ) -> ScenarioOptionRubric | None:
        result = await self._session.execute(
            select(ScenarioOptionRubricORM)
            .where(
                ScenarioOptionRubricORM.scenario_id == scenario_id,
                ScenarioOptionRubricORM.exercise_option_id == exercise_option_id,
            )
            .order_by(ScenarioOptionRubricORM.created_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return await self._to_domain(row)

    async def list_for_scenario(self, scenario_id: UUID) -> list[ScenarioOptionRubric]:
        result = await self._session.execute(
            select(ScenarioOptionRubricORM).where(ScenarioOptionRubricORM.scenario_id == scenario_id)
        )
        rows = result.scalars().all()
        return [await self._to_domain(row) for row in rows]

    async def _get_row(
        self, scenario_id: UUID, exercise_option_id: UUID, rubric_version: str
    ) -> ScenarioOptionRubricORM | None:
        result = await self._session.execute(
            select(ScenarioOptionRubricORM).where(
                ScenarioOptionRubricORM.scenario_id == scenario_id,
                ScenarioOptionRubricORM.exercise_option_id == exercise_option_id,
                ScenarioOptionRubricORM.rubric_version == rubric_version,
            )
        )
        return result.scalar_one_or_none()

    async def _to_domain(self, row: ScenarioOptionRubricORM) -> ScenarioOptionRubric:
        code_result = await self._session.execute(
            select(ScenarioOptionRubricFeedbackCodeORM.feedback_code).where(
                ScenarioOptionRubricFeedbackCodeORM.rubric_id == row.rubric_id
            )
        )
        return scenario_option_rubric_orm_to_domain(row, list(code_result.scalars().all()))
