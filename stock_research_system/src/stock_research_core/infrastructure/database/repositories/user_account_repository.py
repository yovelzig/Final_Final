"""SQLAlchemy repository for `UserAccount` persistence.

`password_hash` only ever crosses this repository's boundary through
`create_account` (write), `change_password_hash` (write), and
`get_credential_by_normalized_email` (the one dedicated read path,
returning an `AccountCredential`) - every other read method returns the
public `UserAccount` domain model, which never contains a password
hash.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.application.identity.ports import AccountCredential
from stock_research_core.domain.identity.enums import AccountRole, AccountStatus
from stock_research_core.domain.identity.models import UserAccount
from stock_research_core.infrastructure.database.mappers.identity_mappers import (
    user_account_credential_from_row,
    user_account_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.user_account import UserAccountORM


class SqlAlchemyUserAccountRepository:
    """Persists and queries `UserAccount` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_account(self, *, account: UserAccount, password_hash: str) -> UserAccount:
        row = UserAccountORM(
            account_id=account.account_id,
            email=account.email,
            normalized_email=account.normalized_email,
            display_name=account.display_name,
            password_hash=password_hash,
            learner_id=account.learner_id,
            role=account.role.value,
            status=account.status.value,
            failed_login_count=account.failed_login_count,
            locked_until=account.locked_until,
            last_login_at=account.last_login_at,
        )
        self._session.add(row)
        await self._session.flush()
        return user_account_orm_to_domain(row)

    async def get_by_id(self, account_id: UUID) -> UserAccount | None:
        row = await self._session.get(UserAccountORM, account_id)
        return user_account_orm_to_domain(row) if row is not None else None

    async def get_by_normalized_email(self, normalized_email: str) -> UserAccount | None:
        statement = select(UserAccountORM).where(UserAccountORM.normalized_email == normalized_email)
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return user_account_orm_to_domain(row) if row is not None else None

    async def get_credential_by_normalized_email(self, normalized_email: str) -> AccountCredential | None:
        statement = select(UserAccountORM).where(UserAccountORM.normalized_email == normalized_email)
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return user_account_credential_from_row(row) if row is not None else None

    async def get_for_update(self, account_id: UUID) -> UserAccount | None:
        statement = select(UserAccountORM).where(UserAccountORM.account_id == account_id).with_for_update()
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return user_account_orm_to_domain(row) if row is not None else None

    async def normalized_email_exists(self, normalized_email: str) -> bool:
        statement = select(func.count()).select_from(UserAccountORM).where(
            UserAccountORM.normalized_email == normalized_email
        )
        result = await self._session.execute(statement)
        return int(result.scalar_one()) > 0

    async def update_status(
        self, account_id: UUID, *, status: AccountStatus, locked_until: datetime | None
    ) -> UserAccount:
        row = await self._session.get(UserAccountORM, account_id)
        if row is None:
            raise PersistenceError(f"No user account found with id '{account_id}'.")
        row.status = status.value
        row.locked_until = locked_until
        await self._session.flush()
        await self._session.refresh(row)
        return user_account_orm_to_domain(row)

    async def update_login_counters(
        self,
        account_id: UUID,
        *,
        failed_login_count: int,
        last_login_at: datetime | None = None,
        status: AccountStatus | None = None,
        locked_until: datetime | None = None,
    ) -> UserAccount:
        row = await self._session.get(UserAccountORM, account_id)
        if row is None:
            raise PersistenceError(f"No user account found with id '{account_id}'.")
        row.failed_login_count = failed_login_count
        if last_login_at is not None:
            row.last_login_at = last_login_at
        if status is not None:
            row.status = status.value
            row.locked_until = locked_until
        await self._session.flush()
        await self._session.refresh(row)
        return user_account_orm_to_domain(row)

    async def link_learner(self, account_id: UUID, learner_id: UUID) -> UserAccount:
        row = await self._session.get(UserAccountORM, account_id)
        if row is None:
            raise PersistenceError(f"No user account found with id '{account_id}'.")
        row.learner_id = learner_id
        await self._session.flush()
        await self._session.refresh(row)
        return user_account_orm_to_domain(row)

    async def change_password_hash(self, account_id: UUID, *, password_hash: str) -> UserAccount:
        row = await self._session.get(UserAccountORM, account_id)
        if row is None:
            raise PersistenceError(f"No user account found with id '{account_id}'.")
        row.password_hash = password_hash
        await self._session.flush()
        await self._session.refresh(row)
        return user_account_orm_to_domain(row)

    async def list_accounts(
        self,
        *,
        role: AccountRole | None = None,
        status: AccountStatus | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[UserAccount], int]:
        statement = select(UserAccountORM)
        count_statement = select(func.count()).select_from(UserAccountORM)
        if role is not None:
            statement = statement.where(UserAccountORM.role == role.value)
            count_statement = count_statement.where(UserAccountORM.role == role.value)
        if status is not None:
            statement = statement.where(UserAccountORM.status == status.value)
            count_statement = count_statement.where(UserAccountORM.status == status.value)
        statement = statement.order_by(UserAccountORM.created_at.asc()).limit(limit).offset(offset)

        total = int((await self._session.execute(count_statement)).scalar_one())
        result = await self._session.execute(statement)
        accounts = [user_account_orm_to_domain(row) for row in result.scalars().all()]
        return accounts, total
