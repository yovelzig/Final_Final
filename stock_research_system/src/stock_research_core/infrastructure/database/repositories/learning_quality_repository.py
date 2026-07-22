"""SQLAlchemy repository for `LearningQualityAggregate` persistence
(Phase 13). Aggregation jobs are safe to retry: `upsert` is keyed on the
exact same tuple as the table's uniqueness constraint (metric type,
period, cohort key, calculation version, filter hash), so a retried
aggregation job recomputes and replaces its own prior result rather than
creating a duplicate row."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.domain.quality_evaluation.enums import LearningOutcomeMetricType
from stock_research_core.domain.quality_evaluation.models import LearningQualityAggregate
from stock_research_core.infrastructure.database.mappers.quality_evaluation_mappers import (
    learning_quality_aggregate_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.learning_quality_aggregate import LearningQualityAggregateORM


def filter_hash(filters: dict) -> str:
    """A stable, lowercase-hex SHA-256 digest of `filters` - the tuple
    (metric_type, period, cohort_key, calculation_version, filter_hash)
    is the aggregate's uniqueness identity (spec section 19)."""
    canonical = json.dumps(filters, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SqlAlchemyLearningQualityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_aggregate(self, aggregate: LearningQualityAggregate) -> LearningQualityAggregate:
        computed_hash = filter_hash(aggregate.filters)
        statement = pg_insert(LearningQualityAggregateORM).values(
            aggregate_id=aggregate.aggregate_id, metric_type=aggregate.metric_type.value,
            period_start=aggregate.period_start, period_end=aggregate.period_end, cohort_key=aggregate.cohort_key,
            cohort_size=aggregate.cohort_size, value=aggregate.value, sample_count=aggregate.sample_count,
            calculation_version=aggregate.calculation_version, filters=dict(aggregate.filters),
            filter_hash=computed_hash,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_learning_quality_aggregates_identity",
            set_={
                "cohort_size": aggregate.cohort_size, "value": aggregate.value,
                "sample_count": aggregate.sample_count,
            },
        ).returning(LearningQualityAggregateORM)
        result = await self._session.execute(statement)
        row = result.scalar_one()
        await self._session.flush()
        return learning_quality_aggregate_orm_to_domain(row)

    async def get_by_id(self, aggregate_id: UUID) -> LearningQualityAggregate | None:
        row = await self._session.get(LearningQualityAggregateORM, aggregate_id)
        return learning_quality_aggregate_orm_to_domain(row) if row is not None else None

    async def list_for_metric_and_period(
        self, *, metric_type: LearningOutcomeMetricType, period_start, period_end, cohort_key: str | None = None,
    ) -> list[LearningQualityAggregate]:
        statement = select(LearningQualityAggregateORM).where(
            LearningQualityAggregateORM.metric_type == metric_type.value,
            LearningQualityAggregateORM.period_start >= period_start,
            LearningQualityAggregateORM.period_end <= period_end,
        )
        if cohort_key is not None:
            statement = statement.where(LearningQualityAggregateORM.cohort_key == cohort_key)
        statement = statement.order_by(LearningQualityAggregateORM.period_start)
        result = await self._session.execute(statement)
        return [learning_quality_aggregate_orm_to_domain(row) for row in result.scalars().all()]
