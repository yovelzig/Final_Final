"""SQLAlchemy repository for `TrackedSecurity` persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.models import TrackedSecurity
from stock_research_core.infrastructure.database.mappers.tracked_security_mapper import (
    tracked_security_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.tracked_security import TrackedSecurityORM


class SqlAlchemyTrackedSecurityRepository:
    """Persists and queries `TrackedSecurity` rows.

    The `security_id` foreign key (RESTRICT) guarantees a security
    cannot be tracked before it exists in `securities`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, tracked_security: TrackedSecurity) -> TrackedSecurity:
        insert_stmt = pg_insert(TrackedSecurityORM).values(
            security_id=tracked_security.security_id,
            enabled=tracked_security.enabled,
            monitoring_started_at=tracked_security.monitoring_started_at,
            last_successful_update_at=tracked_security.last_successful_update_at,
            next_scheduled_update_at=tracked_security.next_scheduled_update_at,
            alert_threshold_probability_change=tracked_security.alert_threshold_probability_change,
            alert_threshold_expected_return_change=(
                tracked_security.alert_threshold_expected_return_change
            ),
        )
        statement = insert_stmt.on_conflict_do_update(
            index_elements=["security_id"],
            set_={
                "enabled": insert_stmt.excluded.enabled,
                "last_successful_update_at": insert_stmt.excluded.last_successful_update_at,
                "next_scheduled_update_at": insert_stmt.excluded.next_scheduled_update_at,
                "alert_threshold_probability_change": (
                    insert_stmt.excluded.alert_threshold_probability_change
                ),
                "alert_threshold_expected_return_change": (
                    insert_stmt.excluded.alert_threshold_expected_return_change
                ),
                "updated_at": func.now(),
            },
        )

        try:
            await self._session.execute(statement)
        except IntegrityError as exc:
            raise PersistenceError(
                f"Cannot track security '{tracked_security.security_id}': the security "
                "does not exist. Store the Security first."
            ) from exc

        row = await self._session.get(TrackedSecurityORM, tracked_security.security_id)
        assert row is not None
        return tracked_security_orm_to_domain(row)

    async def get(self, security_id: UUID) -> TrackedSecurity | None:
        row = await self._session.get(TrackedSecurityORM, security_id)
        return tracked_security_orm_to_domain(row) if row is not None else None

    async def list_enabled(self) -> list[TrackedSecurity]:
        statement = select(TrackedSecurityORM).where(TrackedSecurityORM.enabled.is_(True))
        result = await self._session.execute(statement)
        return [tracked_security_orm_to_domain(row) for row in result.scalars().all()]

    async def set_enabled(self, security_id: UUID, enabled: bool) -> TrackedSecurity:
        row = await self._get_or_raise(security_id)
        row.enabled = enabled
        await self._session.flush()
        return tracked_security_orm_to_domain(row)

    async def update_last_successful_update(
        self, security_id: UUID, timestamp: datetime
    ) -> TrackedSecurity:
        row = await self._get_or_raise(security_id)
        row.last_successful_update_at = timestamp
        await self._session.flush()
        return tracked_security_orm_to_domain(row)

    async def _get_or_raise(self, security_id: UUID) -> TrackedSecurityORM:
        row = await self._session.get(TrackedSecurityORM, security_id)
        if row is None:
            raise PersistenceError(f"No tracked security found with id '{security_id}'.")
        return row
