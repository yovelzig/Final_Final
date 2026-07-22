"""SQLAlchemy repository for `PortfolioDecisionJournalEntry` persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.virtual_portfolio.models import PortfolioDecisionJournalEntry
from stock_research_core.infrastructure.database.mappers.virtual_portfolio_mappers import (
    portfolio_decision_journal_entry_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.portfolio_decision_journal import (
    PortfolioDecisionJournalEntryORM,
    PortfolioJournalAssumptionORM,
    PortfolioJournalInformationItemORM,
    PortfolioJournalRiskTagORM,
)

_DEFAULT_LIST_LIMIT = 20


class SqlAlchemyPortfolioJournalRepository:
    """Persists and queries `PortfolioDecisionJournalEntry` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entry: PortfolioDecisionJournalEntry) -> PortfolioDecisionJournalEntry:
        row = PortfolioDecisionJournalEntryORM(
            journal_entry_id=entry.journal_entry_id,
            portfolio_id=entry.portfolio_id,
            learner_id=entry.learner_id,
            security_id=entry.security_id,
            related_transaction_id=entry.related_transaction_id,
            action=entry.action.value,
            decision_at=entry.decision_at,
            rationale=entry.rationale,
            expected_horizon_days=entry.expected_horizon_days,
            confidence=entry.confidence.value,
        )
        self._session.add(row)
        for tag in entry.risk_tags:
            self._session.add(PortfolioJournalRiskTagORM(journal_entry_id=entry.journal_entry_id, risk_tag=tag))
        for item in entry.information_considered:
            self._session.add(
                PortfolioJournalInformationItemORM(
                    journal_entry_id=entry.journal_entry_id, information_item=item
                )
            )
        for assumption in entry.assumptions:
            self._session.add(
                PortfolioJournalAssumptionORM(
                    journal_entry_id=entry.journal_entry_id, assumption=assumption
                )
            )
        await self._session.flush()
        return portfolio_decision_journal_entry_orm_to_domain(
            row, list(entry.risk_tags), list(entry.information_considered), list(entry.assumptions)
        )

    async def link_to_transaction(
        self, journal_entry_id: UUID, transaction_id: UUID
    ) -> PortfolioDecisionJournalEntry:
        row = await self._session.get(PortfolioDecisionJournalEntryORM, journal_entry_id)
        if row is None:
            raise PersistenceError(f"No decision journal entry found with id '{journal_entry_id}'.")
        row.related_transaction_id = transaction_id
        await self._session.flush()
        await self._session.refresh(row)
        risk_tags, information_items, assumptions = await self._load_lists(journal_entry_id)
        return portfolio_decision_journal_entry_orm_to_domain(row, risk_tags, information_items, assumptions)

    async def get(self, journal_entry_id: UUID) -> PortfolioDecisionJournalEntry | None:
        row = await self._session.get(PortfolioDecisionJournalEntryORM, journal_entry_id)
        if row is None:
            return None
        risk_tags, information_items, assumptions = await self._load_lists(journal_entry_id)
        return portfolio_decision_journal_entry_orm_to_domain(row, risk_tags, information_items, assumptions)

    async def get_by_transaction(self, transaction_id: UUID) -> PortfolioDecisionJournalEntry | None:
        statement = select(PortfolioDecisionJournalEntryORM).where(
            PortfolioDecisionJournalEntryORM.related_transaction_id == transaction_id
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        if row is None:
            return None
        risk_tags, information_items, assumptions = await self._load_lists(row.journal_entry_id)
        return portfolio_decision_journal_entry_orm_to_domain(row, risk_tags, information_items, assumptions)

    async def list_for_portfolio(
        self, portfolio_id: UUID, limit: int = _DEFAULT_LIST_LIMIT
    ) -> list[PortfolioDecisionJournalEntry]:
        statement = (
            select(PortfolioDecisionJournalEntryORM)
            .where(PortfolioDecisionJournalEntryORM.portfolio_id == portfolio_id)
            .order_by(PortfolioDecisionJournalEntryORM.decision_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        rows = result.scalars().all()
        entries = []
        for row in rows:
            risk_tags, information_items, assumptions = await self._load_lists(row.journal_entry_id)
            entries.append(
                portfolio_decision_journal_entry_orm_to_domain(row, risk_tags, information_items, assumptions)
            )
        return entries

    async def list_for_security(
        self, portfolio_id: UUID, security_id: UUID
    ) -> list[PortfolioDecisionJournalEntry]:
        statement = (
            select(PortfolioDecisionJournalEntryORM)
            .where(
                PortfolioDecisionJournalEntryORM.portfolio_id == portfolio_id,
                PortfolioDecisionJournalEntryORM.security_id == security_id,
            )
            .order_by(PortfolioDecisionJournalEntryORM.decision_at.desc())
        )
        result = await self._session.execute(statement)
        rows = result.scalars().all()
        entries = []
        for row in rows:
            risk_tags, information_items, assumptions = await self._load_lists(row.journal_entry_id)
            entries.append(
                portfolio_decision_journal_entry_orm_to_domain(row, risk_tags, information_items, assumptions)
            )
        return entries

    async def _load_lists(self, journal_entry_id: UUID) -> tuple[list[str], list[str], list[str]]:
        risk_tags = (
            await self._session.execute(
                select(PortfolioJournalRiskTagORM.risk_tag).where(
                    PortfolioJournalRiskTagORM.journal_entry_id == journal_entry_id
                )
            )
        ).scalars().all()
        information_items = (
            await self._session.execute(
                select(PortfolioJournalInformationItemORM.information_item).where(
                    PortfolioJournalInformationItemORM.journal_entry_id == journal_entry_id
                )
            )
        ).scalars().all()
        assumptions = (
            await self._session.execute(
                select(PortfolioJournalAssumptionORM.assumption).where(
                    PortfolioJournalAssumptionORM.journal_entry_id == journal_entry_id
                )
            )
        ).scalars().all()
        return list(risk_tags), list(information_items), list(assumptions)
