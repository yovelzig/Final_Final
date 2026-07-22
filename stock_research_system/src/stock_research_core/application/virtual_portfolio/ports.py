"""Application-level repository Protocols for the virtual-portfolio engine.

Pure `Protocol` definitions - no SQLAlchemy (or any other infrastructure
library) is imported here. Concrete implementations live under
`stock_research_core.infrastructure.database`. Policy Protocols
(`TradeExecutionPolicyPort`, `PortfolioAccountingPolicyPort`,
`PortfolioAnalyticsPort`, `PortfolioFeedbackPolicyPort`) live alongside
their own concrete implementations in `execution.py`, `analytics.py`,
and `feedback.py`, matching the convention already used by
`application.market_scenarios.calculator`/`grading`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from stock_research_core.domain.virtual_portfolio.enums import PortfolioValuationRunStatus
from stock_research_core.domain.virtual_portfolio.models import (
    PortfolioDecisionJournalEntry,
    PortfolioHolding,
    PortfolioPositionValuation,
    PortfolioRiskAssessment,
    PortfolioTransaction,
    PortfolioValuationRun,
    PortfolioValuationSnapshot,
    VirtualPortfolio,
)


class VirtualPortfolioRepositoryPort(Protocol):
    """Persists and queries `VirtualPortfolio` objects."""

    async def create(self, portfolio: VirtualPortfolio) -> VirtualPortfolio: ...

    async def get(self, portfolio_id: UUID, *, for_update: bool = False) -> VirtualPortfolio | None: ...

    async def list_for_learner(
        self, learner_id: UUID, active_only: bool = False
    ) -> list[VirtualPortfolio]: ...

    async def update(self, portfolio: VirtualPortfolio) -> VirtualPortfolio: ...

    async def list_all_active_ids(self, *, limit: int = 10_000) -> list[UUID]:
        """All `ACTIVE` portfolio IDs system-wide, bounded by `limit`.

        Added for Phase 11's `PORTFOLIO_BATCH_VALUATION` job
        `all_active_portfolios` mode - an operational, system-wide
        variant of `list_for_learner`, not a learner-facing query."""
        ...


class PortfolioTransactionRepositoryPort(Protocol):
    """Persists and queries `PortfolioTransaction` objects."""

    async def create_pending(self, transaction: PortfolioTransaction) -> PortfolioTransaction: ...

    async def get(self, transaction_id: UUID) -> PortfolioTransaction | None: ...

    async def get_by_idempotency_key(
        self, portfolio_id: UUID, idempotency_key: str
    ) -> PortfolioTransaction | None: ...

    async def mark_executed(self, transaction: PortfolioTransaction) -> PortfolioTransaction: ...

    async def mark_rejected(self, transaction: PortfolioTransaction) -> PortfolioTransaction: ...

    async def list_for_portfolio(
        self,
        portfolio_id: UUID,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[PortfolioTransaction]: ...


class PortfolioHoldingRepositoryPort(Protocol):
    """Persists and queries `PortfolioHolding` objects. Unique per (portfolio, security)."""

    async def get(
        self, portfolio_id: UUID, security_id: UUID, *, for_update: bool = False
    ) -> PortfolioHolding | None: ...

    async def list_for_portfolio(
        self, portfolio_id: UUID, include_zero: bool = False
    ) -> list[PortfolioHolding]: ...

    async def upsert(self, holding: PortfolioHolding) -> PortfolioHolding: ...


class PortfolioJournalRepositoryPort(Protocol):
    """Persists and queries `PortfolioDecisionJournalEntry` objects."""

    async def create(self, entry: PortfolioDecisionJournalEntry) -> PortfolioDecisionJournalEntry: ...

    async def link_to_transaction(
        self, journal_entry_id: UUID, transaction_id: UUID
    ) -> PortfolioDecisionJournalEntry: ...

    async def get(self, journal_entry_id: UUID) -> PortfolioDecisionJournalEntry | None: ...

    async def get_by_transaction(self, transaction_id: UUID) -> PortfolioDecisionJournalEntry | None:
        """Not in the original spec method list, but required for a clean
        idempotent trade replay (`VirtualPortfolioService.execute_trade`
        needs to recover the journal entry linked to an already-executed
        transaction when the same idempotency key is retried) - the same
        kind of minimal, necessary lookup-by-id addition already used
        elsewhere in this codebase."""
        ...

    async def list_for_portfolio(
        self, portfolio_id: UUID, limit: int = 20
    ) -> list[PortfolioDecisionJournalEntry]: ...

    async def list_for_security(
        self, portfolio_id: UUID, security_id: UUID
    ) -> list[PortfolioDecisionJournalEntry]: ...


class PortfolioValuationRepositoryPort(Protocol):
    """Persists and queries `PortfolioValuationSnapshot` / `PortfolioPositionValuation` objects."""

    async def upsert_snapshot(self, snapshot: PortfolioValuationSnapshot) -> PortfolioValuationSnapshot: ...

    async def upsert_positions(
        self, positions: list[PortfolioPositionValuation]
    ) -> list[PortfolioPositionValuation]: ...

    async def get_latest(self, portfolio_id: UUID) -> PortfolioValuationSnapshot | None: ...

    async def get_by_as_of(
        self, portfolio_id: UUID, as_of: datetime, valuation_version: str
    ) -> PortfolioValuationSnapshot | None: ...

    async def list_range(
        self, portfolio_id: UUID, start_at: datetime, end_at: datetime
    ) -> list[PortfolioValuationSnapshot]: ...

    async def list_positions(self, snapshot_id: UUID) -> list[PortfolioPositionValuation]: ...


class PortfolioRiskRepositoryPort(Protocol):
    """Persists and queries `PortfolioRiskAssessment` objects."""

    async def upsert(self, assessment: PortfolioRiskAssessment) -> PortfolioRiskAssessment: ...

    async def get_by_snapshot(
        self, snapshot_id: UUID, policy_version: str
    ) -> PortfolioRiskAssessment | None: ...

    async def get_latest(self, portfolio_id: UUID) -> PortfolioRiskAssessment | None: ...

    async def list_history(self, portfolio_id: UUID, limit: int = 20) -> list[PortfolioRiskAssessment]: ...


class PortfolioValuationRunRepositoryPort(Protocol):
    """Persists and queries `PortfolioValuationRun` audit records."""

    async def create_started(self, run: PortfolioValuationRun) -> PortfolioValuationRun: ...

    async def mark_completed(
        self, run_id: UUID, *, completed_at: datetime, priced_holding_count: int, missing_price_count: int
    ) -> PortfolioValuationRun: ...

    async def mark_failed(
        self, run_id: UUID, *, completed_at: datetime, error_type: str, error_message: str
    ) -> PortfolioValuationRun: ...

    async def mark_no_price_data(
        self, run_id: UUID, *, completed_at: datetime, missing_price_count: int
    ) -> PortfolioValuationRun: ...

    async def get(self, run_id: UUID) -> PortfolioValuationRun | None: ...

    async def list_recent(self, portfolio_id: UUID, limit: int = 10) -> list[PortfolioValuationRun]: ...
