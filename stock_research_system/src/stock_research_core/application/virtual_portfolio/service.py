"""Application service orchestrating virtual portfolios and trades.

This module depends only on domain models, application result models,
and `Protocol` contracts (`UnitOfWorkPort`, `TradeExecutionPolicyPort`,
`PortfolioAccountingPolicyPort`). It never instantiates a concrete
engine, session, or repository, and never calls `datetime.now()`
directly - time comes from an injected `clock` callable so tests are
fully deterministic. It never calls yfinance and never reads a
`MarketBar` after the relevant point in time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable
from uuid import UUID

from stock_research_core.application.exceptions import (
    InactiveLearnerError,
    InvalidPortfolioStateError,
    LearnerNotFoundError,
    SecurityNotFoundError,
    TradeRejectedError,
    VirtualPortfolioNotFoundError,
)
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.application.virtual_portfolio.execution import (
    PortfolioAccountingPolicyPort,
    TradeExecutionPolicyPort,
)
from stock_research_core.application.virtual_portfolio.models import (
    PortfolioOverview,
    TradeExecutionResult,
    TradePreview,
)
from stock_research_core.domain.models import utc_now
from stock_research_core.domain.virtual_portfolio.enums import (
    DecisionConfidence,
    PortfolioDecisionAction,
    PortfolioTransactionStatus,
    PortfolioTransactionType,
    TradeRejectionReason,
    VirtualPortfolioStatus,
)
from stock_research_core.domain.virtual_portfolio.models import (
    PortfolioDecisionJournalEntry,
    PortfolioTransaction,
    VirtualPortfolio,
)

Clock = Callable[[], datetime]

PORTFOLIO_VERSION = "virtual-portfolio-v1"

#: Only these non-trade decisions are supported by `record_non_trade_decision` -
#: BUY/SELL always flow through `execute_trade` instead.
_NON_TRADE_ACTIONS = frozenset(
    {PortfolioDecisionAction.HOLD, PortfolioDecisionAction.REBALANCE, PortfolioDecisionAction.RESEARCH_MORE}
)

_DEFAULT_TRANSACTION_INTERVAL = "1d"
_DEFAULT_RECENT_LIMIT = 20


class VirtualPortfolioService:
    """Orchestrates portfolio creation, trade preview/execution, and decision journaling."""

    def __init__(
        self,
        unit_of_work_factory: Callable[[], UnitOfWorkPort],
        execution_policy: TradeExecutionPolicyPort,
        accounting_policy: PortfolioAccountingPolicyPort,
        clock: Clock = utc_now,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._execution_policy = execution_policy
        self._accounting_policy = accounting_policy
        self._clock = clock

    # -- portfolio lifecycle ---------------------------------------------------------

    async def create_portfolio(
        self,
        *,
        learner_id: UUID,
        name: str,
        initial_cash: float,
        simulation_start_at: datetime,
        benchmark_ticker: str | None = None,
        allow_fractional_shares: bool = True,
        require_decision_journal: bool = True,
        fixed_transaction_fee: float = 0.0,
        transaction_fee_bps: float = 0.0,
    ) -> VirtualPortfolio:
        async with self._unit_of_work_factory() as uow:
            learner = await uow.learners.get(learner_id)
            if learner is None:
                raise LearnerNotFoundError(f"No learner found with id '{learner_id}'.")
            if not learner.active:
                raise InactiveLearnerError(f"Learner '{learner_id}' is not active.")

            benchmark_security_id = None
            if benchmark_ticker is not None:
                benchmark_security = await uow.securities.get_by_ticker(benchmark_ticker)
                if benchmark_security is None:
                    raise SecurityNotFoundError(
                        f"No stored security found for benchmark ticker '{benchmark_ticker}'. "
                        "Only already-ingested securities can be used as a benchmark."
                    )
                if benchmark_security.currency != "USD":
                    raise InvalidPortfolioStateError("Phase 7 officially supports USD-denominated benchmarks only.")
                benchmark_security_id = benchmark_security.security_id

            portfolio = VirtualPortfolio(
                learner_id=learner_id,
                name=name,
                base_currency="USD",
                initial_cash=initial_cash,
                cash_balance=initial_cash,
                benchmark_security_id=benchmark_security_id,
                status=VirtualPortfolioStatus.ACTIVE,
                allow_fractional_shares=allow_fractional_shares,
                require_decision_journal=require_decision_journal,
                fixed_transaction_fee=fixed_transaction_fee,
                transaction_fee_bps=transaction_fee_bps,
                simulation_start_at=simulation_start_at,
                current_simulation_at=simulation_start_at,
                portfolio_version=PORTFOLIO_VERSION,
            )
            created = await uow.virtual_portfolios.create(portfolio)
            await uow.commit()
        return created

    # -- trade preview ---------------------------------------------------------

    async def preview_trade(
        self,
        *,
        portfolio_id: UUID,
        ticker: str,
        transaction_type: PortfolioTransactionType,
        quantity: float,
        requested_at: datetime,
    ) -> TradePreview:
        async with self._unit_of_work_factory() as uow:
            portfolio = await uow.virtual_portfolios.get(portfolio_id)
            if portfolio is None:
                raise VirtualPortfolioNotFoundError(f"No virtual portfolio found with id '{portfolio_id}'.")

            security = await uow.securities.get_by_ticker(ticker)
            if security is None:
                raise SecurityNotFoundError(f"No stored security found for ticker '{ticker}'.")

            existing_holding = await uow.portfolio_holdings.get(portfolio_id, security.security_id)
            holdings = [existing_holding] if existing_holding is not None else []

            next_bar = await uow.market_bars.get_next_bar_after(security.security_id, requested_at)
            market_bars = [next_bar] if next_bar is not None else []

            return await self._execution_policy.preview(
                portfolio=portfolio,
                security=security,
                holdings=holdings,
                transaction_type=transaction_type,
                quantity=quantity,
                requested_at=requested_at,
                market_bars=market_bars,
            )

    # -- trade execution ---------------------------------------------------------

    async def execute_trade(
        self,
        *,
        portfolio_id: UUID,
        ticker: str,
        transaction_type: PortfolioTransactionType,
        quantity: float,
        requested_at: datetime,
        idempotency_key: str,
        journal_entry: PortfolioDecisionJournalEntry | None,
    ) -> TradeExecutionResult:
        now = self._clock()
        async with self._unit_of_work_factory() as uow:
            portfolio = await uow.virtual_portfolios.get(portfolio_id, for_update=True)
            if portfolio is None:
                raise VirtualPortfolioNotFoundError(f"No virtual portfolio found with id '{portfolio_id}'.")

            existing_transaction = await uow.portfolio_transactions.get_by_idempotency_key(
                portfolio_id, idempotency_key
            )
            if existing_transaction is not None:
                return await self._replay_existing_transaction(uow, portfolio, existing_transaction)

            if portfolio.status != VirtualPortfolioStatus.ACTIVE:
                raise InvalidPortfolioStateError(f"Portfolio '{portfolio_id}' is not ACTIVE.")
            if requested_at < portfolio.current_simulation_at:
                raise TradeRejectedError(
                    TradeRejectionReason.SIMULATION_DATE_REGRESSION,
                    "requested_at cannot precede the portfolio's current simulation time.",
                )
            if portfolio.require_decision_journal and journal_entry is None:
                raise InvalidPortfolioStateError(
                    f"Portfolio '{portfolio_id}' requires a decision journal entry for every trade."
                )

            security = await uow.securities.get_by_ticker(ticker)
            if security is None:
                raise SecurityNotFoundError(f"No stored security found for ticker '{ticker}'.")

            existing_holding = await uow.portfolio_holdings.get(
                portfolio_id, security.security_id, for_update=True
            )
            holdings = [existing_holding] if existing_holding is not None else []
            next_bar = await uow.market_bars.get_next_bar_after(security.security_id, requested_at)
            market_bars = [next_bar] if next_bar is not None else []

            try:
                preview = await self._execution_policy.preview(
                    portfolio=portfolio,
                    security=security,
                    holdings=holdings,
                    transaction_type=transaction_type,
                    quantity=quantity,
                    requested_at=requested_at,
                    market_bars=market_bars,
                )
            except TradeRejectedError as exc:
                rejected = PortfolioTransaction(
                    portfolio_id=portfolio_id,
                    security_id=security.security_id,
                    transaction_type=transaction_type,
                    status=PortfolioTransactionStatus.REJECTED,
                    requested_at=requested_at,
                    requested_quantity=quantity,
                    source_name="virtual-portfolio-simulation",
                    interval=_DEFAULT_TRANSACTION_INTERVAL,
                    execution_rule_version=self._execution_policy.execution_rule_version,
                    idempotency_key=idempotency_key,
                    rejection_reason=exc.reason,
                    rejection_message=exc.message,
                    updated_at=now,
                )
                await uow.portfolio_transactions.create_pending(rejected)
                await uow.commit()
                raise

            pending = PortfolioTransaction(
                portfolio_id=portfolio_id,
                security_id=security.security_id,
                transaction_type=transaction_type,
                status=PortfolioTransactionStatus.PENDING,
                requested_at=requested_at,
                requested_quantity=quantity,
                source_name="virtual-portfolio-simulation",
                interval=_DEFAULT_TRANSACTION_INTERVAL,
                execution_rule_version=self._execution_policy.execution_rule_version,
                idempotency_key=idempotency_key,
                updated_at=now,
            )
            created_transaction = await uow.portfolio_transactions.create_pending(pending)

            fee = self._accounting_policy.calculate_fee(portfolio=portfolio, gross_amount=preview.gross_amount)
            if transaction_type == PortfolioTransactionType.BUY:
                updated_holding = self._accounting_policy.apply_buy(
                    holding=existing_holding,
                    portfolio_id=portfolio_id,
                    security_id=security.security_id,
                    quantity=quantity,
                    execution_price=preview.expected_execution_price,
                    fee=fee,
                    executed_at=preview.expected_execution_at,
                )
            else:
                assert existing_holding is not None
                updated_holding, _realized_pnl = self._accounting_policy.apply_sell(
                    holding=existing_holding,
                    quantity=quantity,
                    execution_price=preview.expected_execution_price,
                    fee=fee,
                    executed_at=preview.expected_execution_at,
                )
            stored_holding = await uow.portfolio_holdings.upsert(updated_holding)

            executed_transaction = created_transaction.model_copy(
                update={
                    "status": PortfolioTransactionStatus.EXECUTED,
                    "executed_at": preview.expected_execution_at,
                    "executed_quantity": quantity,
                    "execution_price": preview.expected_execution_price,
                    "gross_amount": preview.gross_amount,
                    "fee_amount": fee,
                    "net_cash_effect": preview.estimated_cash_effect,
                    "updated_at": now,
                }
            )
            stored_transaction = await uow.portfolio_transactions.mark_executed(executed_transaction)

            stored_journal_entry = None
            if journal_entry is not None:
                rewritten_entry = journal_entry.model_copy(
                    update={
                        "portfolio_id": portfolio_id,
                        "learner_id": portfolio.learner_id,
                        "security_id": security.security_id,
                        "related_transaction_id": stored_transaction.transaction_id,
                    }
                )
                created_entry = await uow.portfolio_journal.create(rewritten_entry)
                stored_journal_entry = await uow.portfolio_journal.link_to_transaction(
                    created_entry.journal_entry_id, stored_transaction.transaction_id
                )

            updated_portfolio = portfolio.model_copy(
                update={
                    "cash_balance": max(0.0, portfolio.cash_balance + preview.estimated_cash_effect),
                    "current_simulation_at": max(
                        portfolio.current_simulation_at, preview.expected_execution_at
                    ),
                    "updated_at": now,
                }
            )
            stored_portfolio = await uow.virtual_portfolios.update(updated_portfolio)

            await uow.commit()

        return TradeExecutionResult(
            transaction=stored_transaction,
            portfolio=stored_portfolio,
            holding=stored_holding,
            journal_entry=stored_journal_entry,
        )

    async def _replay_existing_transaction(
        self, uow: UnitOfWorkPort, portfolio: VirtualPortfolio, transaction: PortfolioTransaction
    ) -> TradeExecutionResult:
        """Idempotent replay: the same `idempotency_key` was already processed.

        Returns the same result as before (or re-raises the same
        rejection) instead of re-executing the trade.
        """
        if transaction.status == PortfolioTransactionStatus.REJECTED:
            assert transaction.rejection_reason is not None
            raise TradeRejectedError(transaction.rejection_reason, transaction.rejection_message or "")

        holding = await uow.portfolio_holdings.get(portfolio.portfolio_id, transaction.security_id)
        assert holding is not None
        journal_entry = await uow.portfolio_journal.get_by_transaction(transaction.transaction_id)
        return TradeExecutionResult(
            transaction=transaction, portfolio=portfolio, holding=holding, journal_entry=journal_entry
        )

    # -- non-trade decisions ---------------------------------------------------------

    async def record_non_trade_decision(
        self,
        *,
        portfolio_id: UUID,
        security_id: UUID | None,
        action: PortfolioDecisionAction,
        decision_at: datetime,
        rationale: str,
        expected_horizon_days: int | None,
        confidence: DecisionConfidence,
        risk_tags: list[str],
        information_considered: list[str],
        assumptions: list[str],
    ) -> PortfolioDecisionJournalEntry:
        if action not in _NON_TRADE_ACTIONS:
            raise InvalidPortfolioStateError(
                f"'{action.value}' is a trade action; use execute_trade instead of record_non_trade_decision."
            )
        async with self._unit_of_work_factory() as uow:
            portfolio = await uow.virtual_portfolios.get(portfolio_id)
            if portfolio is None:
                raise VirtualPortfolioNotFoundError(f"No virtual portfolio found with id '{portfolio_id}'.")

            entry = PortfolioDecisionJournalEntry(
                portfolio_id=portfolio_id,
                learner_id=portfolio.learner_id,
                security_id=security_id,
                action=action,
                decision_at=decision_at,
                rationale=rationale,
                expected_horizon_days=expected_horizon_days,
                confidence=confidence,
                risk_tags=risk_tags,
                information_considered=information_considered,
                assumptions=assumptions,
            )
            created = await uow.portfolio_journal.create(entry)
            await uow.commit()
        return created

    # -- overview ---------------------------------------------------------

    async def get_overview(self, portfolio_id: UUID) -> PortfolioOverview:
        async with self._unit_of_work_factory() as uow:
            portfolio = await uow.virtual_portfolios.get(portfolio_id)
            if portfolio is None:
                raise VirtualPortfolioNotFoundError(f"No virtual portfolio found with id '{portfolio_id}'.")

            holdings = await uow.portfolio_holdings.list_for_portfolio(portfolio_id)
            latest_valuation = await uow.portfolio_valuations.get_latest(portfolio_id)
            position_valuations = (
                await uow.portfolio_valuations.list_positions(latest_valuation.snapshot_id)
                if latest_valuation is not None
                else []
            )
            latest_risk_assessment = await uow.portfolio_risk.get_latest(portfolio_id)
            recent_transactions = await uow.portfolio_transactions.list_for_portfolio(portfolio_id)
            recent_journal_entries = await uow.portfolio_journal.list_for_portfolio(
                portfolio_id, limit=_DEFAULT_RECENT_LIMIT
            )

        return PortfolioOverview(
            portfolio=portfolio,
            holdings=holdings,
            latest_valuation=latest_valuation,
            position_valuations=position_valuations,
            latest_risk_assessment=latest_risk_assessment,
            recent_transactions=recent_transactions[-_DEFAULT_RECENT_LIMIT:],
            recent_journal_entries=recent_journal_entries,
        )
