"""SQLAlchemy repository for `QualityEvaluationSampleResult`/
`QualityMetricResult` persistence (Phase 13) - grouped together because
metric results are always scoped to a run (and usually a sample result)
already persisted through this same repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.quality_evaluation.models import QualityEvaluationSampleResult, QualityMetricResult
from stock_research_core.infrastructure.database.mappers.quality_evaluation_mappers import (
    quality_evaluation_sample_result_orm_to_domain,
    quality_metric_result_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.quality_evaluation_sample_result import (
    QualityEvaluationSampleCitationORM,
    QualityEvaluationSampleResultORM,
    QualityEvaluationSampleRetrievedChunkORM,
    QualityEvaluationSampleRetrievedDocumentORM,
)
from stock_research_core.infrastructure.database.orm.quality_metric_result import QualityMetricResultORM

#: Bounded bulk-insert batch size (spec section 20: "metric bulk inserts
#: are bounded").
_MAX_METRIC_BULK_INSERT_BATCH = 500


class SqlAlchemyQualityEvaluationResultRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- sample results -----------------------------------------------

    async def create_sample_result(self, sample: QualityEvaluationSampleResult) -> QualityEvaluationSampleResult:
        row = QualityEvaluationSampleResultORM(
            sample_result_id=sample.sample_result_id, run_id=sample.run_id, case_id=sample.case_id,
            status=sample.status.value, generated_response=sample.generated_response,
            observed_guardrail_category=sample.observed_guardrail_category.value if sample.observed_guardrail_category else None,
            observed_intent=sample.observed_intent.value if sample.observed_intent else None,
            observed_route=sample.observed_route.value if sample.observed_route else None,
            observed_action_type=sample.observed_action_type.value if sample.observed_action_type else None,
            observed_interrupt=sample.observed_interrupt, latency_ms=sample.latency_ms,
            retrieval_latency_ms=sample.retrieval_latency_ms, generation_latency_ms=sample.generation_latency_ms,
            input_token_count=sample.input_token_count, output_token_count=sample.output_token_count,
            estimated_cost=sample.estimated_cost, failure_code=sample.failure_code,
            failure_message=sample.failure_message,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise PersistenceError(f"A sample result already exists for run/case ({sample.run_id}/{sample.case_id}).") from exc

        for document_id in sample.retrieved_document_ids:
            self._session.add(
                QualityEvaluationSampleRetrievedDocumentORM(sample_result_id=sample.sample_result_id, document_id=document_id)
            )
        for rank, chunk_id in enumerate(sample.retrieved_context_ids):
            self._session.add(
                QualityEvaluationSampleRetrievedChunkORM(
                    sample_result_id=sample.sample_result_id, chunk_id=chunk_id, rank=rank
                )
            )
        for ordinal, chunk_id in enumerate(sample.citation_chunk_ids):
            self._session.add(
                QualityEvaluationSampleCitationORM(
                    sample_result_id=sample.sample_result_id, chunk_id=chunk_id, ordinal=ordinal
                )
            )
        await self._session.flush()
        return await self.get_sample_result_by_id(sample.sample_result_id)  # type: ignore[return-value]

    async def get_sample_result_by_id(self, sample_result_id: UUID) -> QualityEvaluationSampleResult | None:
        row = await self._session.get(QualityEvaluationSampleResultORM, sample_result_id)
        if row is None:
            return None
        return quality_evaluation_sample_result_orm_to_domain(
            row,
            retrieved_context_ids=await self._retrieved_context_ids(sample_result_id),
            retrieved_document_ids=await self._retrieved_document_ids(sample_result_id),
            citation_chunk_ids=await self._citation_chunk_ids(sample_result_id),
        )

    async def list_sample_results_for_run(
        self, run_id: UUID, *, limit: int = 200, offset: int = 0
    ) -> list[QualityEvaluationSampleResult]:
        statement = (
            select(QualityEvaluationSampleResultORM).where(QualityEvaluationSampleResultORM.run_id == run_id)
            .order_by(QualityEvaluationSampleResultORM.created_at).limit(limit).offset(offset)
        )
        result = await self._session.execute(statement)
        samples: list[QualityEvaluationSampleResult] = []
        for row in result.scalars().all():
            samples.append(
                quality_evaluation_sample_result_orm_to_domain(
                    row,
                    retrieved_context_ids=await self._retrieved_context_ids(row.sample_result_id),
                    retrieved_document_ids=await self._retrieved_document_ids(row.sample_result_id),
                    citation_chunk_ids=await self._citation_chunk_ids(row.sample_result_id),
                )
            )
        return samples

    async def _retrieved_context_ids(self, sample_result_id: UUID) -> list[UUID]:
        statement = (
            select(QualityEvaluationSampleRetrievedChunkORM.chunk_id)
            .where(QualityEvaluationSampleRetrievedChunkORM.sample_result_id == sample_result_id)
            .order_by(QualityEvaluationSampleRetrievedChunkORM.rank)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def _retrieved_document_ids(self, sample_result_id: UUID) -> list[UUID]:
        statement = select(QualityEvaluationSampleRetrievedDocumentORM.document_id).where(
            QualityEvaluationSampleRetrievedDocumentORM.sample_result_id == sample_result_id
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def _citation_chunk_ids(self, sample_result_id: UUID) -> list[UUID]:
        statement = (
            select(QualityEvaluationSampleCitationORM.chunk_id)
            .where(QualityEvaluationSampleCitationORM.sample_result_id == sample_result_id)
            .order_by(QualityEvaluationSampleCitationORM.ordinal)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    # -- metric results -----------------------------------------------

    async def bulk_create_metric_results(self, metrics: list[QualityMetricResult]) -> list[QualityMetricResult]:
        if not metrics:
            return []
        if len(metrics) > _MAX_METRIC_BULK_INSERT_BATCH:
            raise PersistenceError(
                f"Refusing to bulk-insert {len(metrics)} metric results in one call "
                f"(bounded at {_MAX_METRIC_BULK_INSERT_BATCH})."
            )
        rows = [
            QualityMetricResultORM(
                metric_result_id=metric.metric_result_id, run_id=metric.run_id,
                sample_result_id=metric.sample_result_id, metric_name=metric.metric_name,
                metric_type=metric.metric_type.value, metric_version=metric.metric_version, score=metric.score,
                passed=metric.passed, threshold=metric.threshold, details=dict(metric.details),
                evaluator_provider=metric.evaluator_provider, evaluator_model=metric.evaluator_model,
            )
            for metric in metrics
        ]
        self._session.add_all(rows)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise PersistenceError("Duplicate metric result for this run/sample/metric/version.") from exc
        return [quality_metric_result_orm_to_domain(row) for row in rows]

    async def list_metric_results_for_run(self, run_id: UUID) -> list[QualityMetricResult]:
        statement = select(QualityMetricResultORM).where(QualityMetricResultORM.run_id == run_id)
        result = await self._session.execute(statement)
        return [quality_metric_result_orm_to_domain(row) for row in result.scalars().all()]

    async def list_metric_results_for_sample(self, sample_result_id: UUID) -> list[QualityMetricResult]:
        statement = select(QualityMetricResultORM).where(QualityMetricResultORM.sample_result_id == sample_result_id)
        result = await self._session.execute(statement)
        return [quality_metric_result_orm_to_domain(row) for row in result.scalars().all()]
