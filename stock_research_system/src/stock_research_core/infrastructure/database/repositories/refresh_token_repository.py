"""SQLAlchemy repository for `AccountRefreshToken` persistence.

`rotate_token` is the security-critical primitive here: an atomic
`UPDATE ... WHERE token_hash = :hash AND status = 'ACTIVE' ... RETURNING`
(a compare-and-swap). Postgres takes a row lock for the duration of the
UPDATE, so under concurrent refresh attempts against the same token,
the second transaction's `UPDATE` blocks until the first commits, then
re-evaluates `WHERE status = 'ACTIVE'` against the now-committed row and
affects zero rows - guaranteeing at most one successful rotation no
matter how many concurrent requests race for the same refresh token.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.domain.identity.enums import RefreshTokenStatus
from stock_research_core.domain.identity.models import AccountRefreshToken
from stock_research_core.infrastructure.database.mappers.identity_mappers import (
    account_refresh_token_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.account_refresh_token import AccountRefreshTokenORM


class SqlAlchemyRefreshTokenRepository:
    """Persists and queries refresh-token metadata."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_token(self, token: AccountRefreshToken) -> AccountRefreshToken:
        row = AccountRefreshTokenORM(
            refresh_token_id=token.refresh_token_id,
            account_id=token.account_id,
            token_family_id=token.token_family_id,
            token_hash=token.token_hash,
            status=token.status.value,
            issued_at=token.issued_at,
            expires_at=token.expires_at,
            rotated_at=token.rotated_at,
            revoked_at=token.revoked_at,
            replaced_by_token_id=token.replaced_by_token_id,
            user_agent_hash=token.user_agent_hash,
            client_ip_hash=token.client_ip_hash,
        )
        self._session.add(row)
        await self._session.flush()
        return account_refresh_token_orm_to_domain(row)

    async def get_by_hash(self, token_hash: str) -> AccountRefreshToken | None:
        statement = select(AccountRefreshTokenORM).where(AccountRefreshTokenORM.token_hash == token_hash)
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return account_refresh_token_orm_to_domain(row) if row is not None else None

    async def rotate_token(
        self, *, token_hash: str, replacement: AccountRefreshToken, rotated_at: datetime
    ) -> AccountRefreshToken | None:
        # The replacement row must exist before the old row's FK
        # (`replaced_by_token_id`) can reference it.
        new_row = AccountRefreshTokenORM(
            refresh_token_id=replacement.refresh_token_id,
            account_id=replacement.account_id,
            token_family_id=replacement.token_family_id,
            token_hash=replacement.token_hash,
            status=replacement.status.value,
            issued_at=replacement.issued_at,
            expires_at=replacement.expires_at,
            rotated_at=replacement.rotated_at,
            revoked_at=replacement.revoked_at,
            replaced_by_token_id=replacement.replaced_by_token_id,
            user_agent_hash=replacement.user_agent_hash,
            client_ip_hash=replacement.client_ip_hash,
        )
        self._session.add(new_row)
        await self._session.flush()

        statement = (
            update(AccountRefreshTokenORM)
            .where(
                AccountRefreshTokenORM.token_hash == token_hash,
                AccountRefreshTokenORM.status == RefreshTokenStatus.ACTIVE.value,
            )
            .values(
                status=RefreshTokenStatus.ROTATED.value,
                rotated_at=rotated_at,
                replaced_by_token_id=new_row.refresh_token_id,
                updated_at=func.now(),
            )
            .returning(AccountRefreshTokenORM.refresh_token_id)
        )
        result = await self._session.execute(statement)
        rotated_id = result.scalars().first()

        if rotated_id is None:
            # Compare-and-swap lost the race (or genuine reuse): discard the
            # orphaned replacement row so the caller's subsequent
            # `revoke_family` call sees a clean token set.
            await self._session.delete(new_row)
            await self._session.flush()
            return None

        await self._session.flush()
        rotated_row = await self._session.get(AccountRefreshTokenORM, rotated_id)
        assert rotated_row is not None
        return account_refresh_token_orm_to_domain(rotated_row)

    async def revoke_token(self, refresh_token_id: UUID, *, revoked_at: datetime) -> AccountRefreshToken:
        row = await self._session.get(AccountRefreshTokenORM, refresh_token_id)
        if row is not None and row.status in (RefreshTokenStatus.ACTIVE.value, RefreshTokenStatus.ROTATED.value):
            row.status = RefreshTokenStatus.REVOKED.value
            row.revoked_at = revoked_at
            await self._session.flush()
            await self._session.refresh(row)
        assert row is not None
        return account_refresh_token_orm_to_domain(row)

    async def revoke_family(self, token_family_id: UUID, *, revoked_at: datetime) -> int:
        statement = (
            update(AccountRefreshTokenORM)
            .where(
                AccountRefreshTokenORM.token_family_id == token_family_id,
                AccountRefreshTokenORM.status.in_(
                    [RefreshTokenStatus.ACTIVE.value, RefreshTokenStatus.ROTATED.value]
                ),
            )
            .values(status=RefreshTokenStatus.REVOKED.value, revoked_at=revoked_at, updated_at=func.now())
        )
        result = await self._session.execute(statement)
        await self._session.flush()
        return result.rowcount or 0

    async def revoke_all_for_account(self, account_id: UUID, *, revoked_at: datetime) -> int:
        statement = (
            update(AccountRefreshTokenORM)
            .where(
                AccountRefreshTokenORM.account_id == account_id,
                AccountRefreshTokenORM.status.in_(
                    [RefreshTokenStatus.ACTIVE.value, RefreshTokenStatus.ROTATED.value]
                ),
            )
            .values(status=RefreshTokenStatus.REVOKED.value, revoked_at=revoked_at, updated_at=func.now())
        )
        result = await self._session.execute(statement)
        await self._session.flush()
        return result.rowcount or 0

    async def list_active_sessions(self, account_id: UUID) -> list[AccountRefreshToken]:
        statement = (
            select(AccountRefreshTokenORM)
            .where(
                AccountRefreshTokenORM.account_id == account_id,
                AccountRefreshTokenORM.status == RefreshTokenStatus.ACTIVE.value,
            )
            .order_by(AccountRefreshTokenORM.issued_at.desc())
        )
        result = await self._session.execute(statement)
        return [account_refresh_token_orm_to_domain(row) for row in result.scalars().all()]
