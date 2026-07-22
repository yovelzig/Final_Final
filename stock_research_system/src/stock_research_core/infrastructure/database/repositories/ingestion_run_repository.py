"""SQLAlchemy repository for ingestion-run audit records and their quality issues."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.application.market_data.models import DataQualityIssue
from stock_research_core.application.persistence.models import (
    IngestionRunRecord,
    IngestionRunStatus,
)
from stock_research_core.infrastructure.database.orm.ingestion_run import (
    MarketDataIngestionRunORM,
)
from stock_research_core.infrastructure.database.orm.quality_issue import (
    MarketDataQualityIssueORM,
)

_ERROR_TYPE_MAX_LENGTH = 250


def _to_record(row: MarketDataIngestionRunORM) -> IngestionRunRecord:
    return IngestionRunRecord(
        run_id=row.run_id,
        security_id=row.security_id,
        provider_name=row.provider_name,
        interval=row.interval,
        requested_start_at=row.requested_start_at,
        requested_end_at=row.requested_end_at,
        is_incremental=row.is_incremental,
        status=IngestionRunStatus(row.status),
        provider_rows_received=row.provider_rows_received,
        valid_bars_returned=row.valid_bars_returned,
        bars_persisted=row.bars_persisted,
        duplicate_rows_removed=row.duplicate_rows_removed,
        invalid_rows_removed=row.invalid_rows_removed,
        started_at=row.started_at,
        completed_at=row.completed_at,
        error_type=row.error_type,
        error_message=row.error_message,
    )


class SqlAlchemyIngestionRunRepository:
    """Creates and updates `market_data_ingestion_runs` audit records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def start(
        self,
        *,
        security_id: UUID,
        provider_name: str,
        interval: str,
        requested_start_at: datetime,
        requested_end_at: datetime,
        is_incremental: bool,
    ) -> IngestionRunRecord:
        row = MarketDataIngestionRunORM(
            run_id=uuid4(),
            security_id=security_id,
            provider_name=provider_name,
            interval=interval,
            requested_start_at=requested_start_at,
            requested_end_at=requested_end_at,
            is_incremental=is_incremental,
            status=IngestionRunStatus.STARTED.value,
            provider_rows_received=0,
            valid_bars_returned=0,
            bars_persisted=0,
            duplicate_rows_removed=0,
            invalid_rows_removed=0,
            started_at=datetime.now(timezone.utc),
        )
        self._session.add(row)
        await self._session.flush()
        return _to_record(row)

    async def mark_completed(
        self,
        run_id: UUID,
        *,
        provider_rows_received: int,
        valid_bars_returned: int,
        bars_persisted: int,
        duplicate_rows_removed: int,
        invalid_rows_removed: int,
    ) -> IngestionRunRecord:
        row = await self._get_or_raise(run_id)
        row.status = IngestionRunStatus.COMPLETED.value
        row.provider_rows_received = provider_rows_received
        row.valid_bars_returned = valid_bars_returned
        row.bars_persisted = bars_persisted
        row.duplicate_rows_removed = duplicate_rows_removed
        row.invalid_rows_removed = invalid_rows_removed
        row.completed_at = datetime.now(timezone.utc)
        await self._session.flush()
        return _to_record(row)

    async def mark_no_new_data(
        self,
        run_id: UUID,
        *,
        provider_rows_received: int = 0,
        valid_bars_returned: int = 0,
        duplicate_rows_removed: int = 0,
        invalid_rows_removed: int = 0,
    ) -> IngestionRunRecord:
        row = await self._get_or_raise(run_id)
        row.status = IngestionRunStatus.NO_NEW_DATA.value
        row.provider_rows_received = provider_rows_received
        row.valid_bars_returned = valid_bars_returned
        row.bars_persisted = 0
        row.duplicate_rows_removed = duplicate_rows_removed
        row.invalid_rows_removed = invalid_rows_removed
        row.completed_at = datetime.now(timezone.utc)
        await self._session.flush()
        return _to_record(row)

    async def mark_failed(
        self,
        run_id: UUID,
        *,
        error_type: str,
        error_message: str,
    ) -> IngestionRunRecord:
        row = await self._get_or_raise(run_id)
        row.status = IngestionRunStatus.FAILED.value
        row.error_type = error_type[:_ERROR_TYPE_MAX_LENGTH]
        row.error_message = error_message
        row.completed_at = datetime.now(timezone.utc)
        await self._session.flush()
        return _to_record(row)

    async def save_quality_issues(self, run_id: UUID, issues: list[DataQualityIssue]) -> int:
        if not issues:
            return 0
        for issue in issues:
            self._session.add(
                MarketDataQualityIssueORM(
                    issue_id=uuid4(),
                    run_id=run_id,
                    code=issue.code,
                    message=issue.message,
                    severity=issue.severity,
                    timestamp=issue.timestamp,
                )
            )
        await self._session.flush()
        return len(issues)

    async def get_by_id(self, run_id: UUID) -> IngestionRunRecord | None:
        row = await self._session.get(MarketDataIngestionRunORM, run_id)
        return _to_record(row) if row is not None else None

    async def list_recent(self, security_id: UUID, limit: int = 10) -> list[IngestionRunRecord]:
        statement = (
            select(MarketDataIngestionRunORM)
            .where(MarketDataIngestionRunORM.security_id == security_id)
            .order_by(MarketDataIngestionRunORM.started_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return [_to_record(row) for row in result.scalars().all()]

    async def _get_or_raise(self, run_id: UUID) -> MarketDataIngestionRunORM:
        row = await self._session.get(MarketDataIngestionRunORM, run_id)
        if row is None:
            raise PersistenceError(f"No ingestion run found with id '{run_id}'.")
        return row
