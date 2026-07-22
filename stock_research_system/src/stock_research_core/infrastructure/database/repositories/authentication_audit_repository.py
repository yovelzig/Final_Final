"""SQLAlchemy repository for the append-only authentication/security audit log."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.domain.identity.models import AuthenticationAuditEvent
from stock_research_core.infrastructure.database.mappers.identity_mappers import (
    authentication_audit_event_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.authentication_audit_event import (
    AuthenticationAuditEventORM,
)


class SqlAlchemyAuthenticationAuditRepository:
    """Appends and queries immutable authentication/security audit events."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append_event(self, event: AuthenticationAuditEvent) -> AuthenticationAuditEvent:
        row = AuthenticationAuditEventORM(
            event_id=event.event_id,
            account_id=event.account_id,
            event_type=event.event_type.value,
            result=event.result.value,
            correlation_id=event.correlation_id,
            email_hash=event.email_hash,
            client_ip_hash=event.client_ip_hash,
            user_agent_hash=event.user_agent_hash,
            reason_code=event.reason_code,
        )
        self._session.add(row)
        await self._session.flush()
        return authentication_audit_event_orm_to_domain(row)

    async def list_recent_for_account(
        self, account_id: UUID, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[AuthenticationAuditEvent], int]:
        base = select(AuthenticationAuditEventORM).where(AuthenticationAuditEventORM.account_id == account_id)
        total = int(
            (
                await self._session.execute(
                    select(func.count()).select_from(base.subquery())
                )
            ).scalar_one()
        )
        statement = base.order_by(desc(AuthenticationAuditEventORM.created_at)).limit(limit).offset(offset)
        result = await self._session.execute(statement)
        events = [authentication_audit_event_orm_to_domain(row) for row in result.scalars().all()]
        return events, total

    async def list_recent_security_events(
        self, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[AuthenticationAuditEvent], int]:
        total = int((await self._session.execute(select(func.count()).select_from(AuthenticationAuditEventORM))).scalar_one())
        statement = (
            select(AuthenticationAuditEventORM)
            .order_by(desc(AuthenticationAuditEventORM.created_at))
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(statement)
        events = [authentication_audit_event_orm_to_domain(row) for row in result.scalars().all()]
        return events, total
