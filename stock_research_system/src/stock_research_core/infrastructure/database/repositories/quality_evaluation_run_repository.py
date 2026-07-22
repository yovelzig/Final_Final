"""SQLAlchemy repository for `QualityEvaluationRun` persistence (Phase 13)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.quality_evaluation.enums import QualityEvaluationRunStatus
from stock_research_core.domain.quality_evaluation.models import QualityEvaluationRun
from stock_research_core.infrastructure.database.mappers.quality_evaluation_mappers import (
    quality_evaluation_run_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.quality_evaluation_run import QualityEvaluationRunORM


class SqlAlchemyQualityEvaluationRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, run: QualityEvaluationRun, *, idempotency_key: str | None = None) -> QualityEvaluationRun:
        row = QualityEvaluationRunORM(
            run_id=run.run_id, suite_id=run.suite_id, status=run.status.value, mode=run.mode.value,
            requested_by_account_id=run.requested_by_account_id, background_job_id=run.background_job_id,
            system_version=run.system_version, git_commit=run.git_commit,
            retrieval_policy_version=run.retrieval_policy_version, embedding_model=run.embedding_model,
            embedding_version=run.embedding_version, tutor_policy_version=run.tutor_policy_version,
            prompt_version=run.prompt_version, guardrail_version=run.guardrail_version,
            graph_version=run.graph_version, evaluator_provider=run.evaluator_provider,
            evaluator_model=run.evaluator_model, ragas_version=run.ragas_version, case_count=run.case_count,
            dataset_hash=run.dataset_hash, configuration_hash=run.configuration_hash,
            idempotency_key=idempotency_key,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise PersistenceError(f"A run with idempotency key '{idempotency_key}' already exists for this suite.") from exc
        return quality_evaluation_run_orm_to_domain(row)

    async def get_by_id(self, run_id: UUID) -> QualityEvaluationRun | None:
        row = await self._session.get(QualityEvaluationRunORM, run_id)
        return quality_evaluation_run_orm_to_domain(row) if row is not None else None

    async def get_for_update(self, run_id: UUID) -> QualityEvaluationRun | None:
        statement = select(QualityEvaluationRunORM).where(QualityEvaluationRunORM.run_id == run_id).with_for_update()
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return quality_evaluation_run_orm_to_domain(row) if row is not None else None

    async def get_by_suite_and_idempotency_key(
        self, *, suite_id: UUID, idempotency_key: str
    ) -> QualityEvaluationRun | None:
        statement = select(QualityEvaluationRunORM).where(
            QualityEvaluationRunORM.suite_id == suite_id, QualityEvaluationRunORM.idempotency_key == idempotency_key
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return quality_evaluation_run_orm_to_domain(row) if row is not None else None

    async def list_for_suite(self, suite_id: UUID, *, limit: int = 50, offset: int = 0) -> list[QualityEvaluationRun]:
        statement = (
            select(QualityEvaluationRunORM).where(QualityEvaluationRunORM.suite_id == suite_id)
            .order_by(QualityEvaluationRunORM.created_at.desc()).limit(limit).offset(offset)
        )
        result = await self._session.execute(statement)
        return [quality_evaluation_run_orm_to_domain(row) for row in result.scalars().all()]

    async def list_recent(self, *, limit: int = 50, offset: int = 0) -> list[QualityEvaluationRun]:
        statement = select(QualityEvaluationRunORM).order_by(QualityEvaluationRunORM.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(statement)
        return [quality_evaluation_run_orm_to_domain(row) for row in result.scalars().all()]

    async def mark_running(self, run_id: UUID, *, started_at: datetime) -> QualityEvaluationRun:
        return await self._set_status(run_id, status=QualityEvaluationRunStatus.RUNNING, started_at=started_at)

    async def update_progress(
        self, run_id: UUID, *, completed_case_count: int, failed_case_count: int, skipped_case_count: int,
    ) -> QualityEvaluationRun:
        row = await self._get_or_raise(run_id)
        row.completed_case_count = completed_case_count
        row.failed_case_count = failed_case_count
        row.skipped_case_count = skipped_case_count
        await self._session.flush()
        await self._session.refresh(row)
        return quality_evaluation_run_orm_to_domain(row)

    async def mark_succeeded(self, run_id: UUID, *, completed_at: datetime) -> QualityEvaluationRun:
        return await self._set_status(run_id, status=QualityEvaluationRunStatus.SUCCEEDED, completed_at=completed_at)

    async def mark_partially_succeeded(self, run_id: UUID, *, completed_at: datetime) -> QualityEvaluationRun:
        return await self._set_status(
            run_id, status=QualityEvaluationRunStatus.PARTIALLY_SUCCEEDED, completed_at=completed_at
        )

    async def mark_failed(self, run_id: UUID, *, completed_at: datetime) -> QualityEvaluationRun:
        return await self._set_status(run_id, status=QualityEvaluationRunStatus.FAILED, completed_at=completed_at)

    async def mark_cancelled(self, run_id: UUID, *, completed_at: datetime) -> QualityEvaluationRun:
        return await self._set_status(run_id, status=QualityEvaluationRunStatus.CANCELLED, completed_at=completed_at)

    async def _get_or_raise(self, run_id: UUID) -> QualityEvaluationRunORM:
        row = await self._session.get(QualityEvaluationRunORM, run_id)
        if row is None:
            raise PersistenceError(f"Quality evaluation run '{run_id}' not found.")
        return row

    async def _set_status(
        self, run_id: UUID, *, status: QualityEvaluationRunStatus,
        started_at: datetime | None = None, completed_at: datetime | None = None,
    ) -> QualityEvaluationRun:
        row = await self._get_or_raise(run_id)
        row.status = status.value
        if started_at is not None:
            row.started_at = started_at
        if completed_at is not None:
            row.completed_at = completed_at
        await self._session.flush()
        await self._session.refresh(row)
        return quality_evaluation_run_orm_to_domain(row)
