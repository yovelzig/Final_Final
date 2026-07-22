"""CLI for the FinQuest virtual-portfolio and decision-journal engine.

Create a portfolio (PowerShell):

    python -m stock_research_core.cli.virtual_portfolio `
      --learner-id <UUID> --create --name "Learning Portfolio" `
      --initial-cash 10000 --start-date 2024-01-02 --benchmark SPY

View a portfolio overview:

    python -m stock_research_core.cli.virtual_portfolio --portfolio-id <UUID> --overview

Preview a buy:

    python -m stock_research_core.cli.virtual_portfolio `
      --portfolio-id <UUID> --preview-buy NVDA --quantity 5 --requested-at 2024-02-01

Execute a buy with a decision journal entry:

    python -m stock_research_core.cli.virtual_portfolio `
      --portfolio-id <UUID> --buy NVDA --quantity 5 --requested-at 2024-02-01 `
      --idempotency-key buy-nvda-001 --confidence MEDIUM --horizon-days 365 `
      --rationale "Limited exposure as part of a diversified simulation." `
      --risk-tag concentration --risk-tag volatility

Value a portfolio:

    python -m stock_research_core.cli.virtual_portfolio --portfolio-id <UUID> --value-at 2024-12-31

This module is a composition root: it is the one place outside the
infrastructure layer allowed to import concrete adapters directly.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from uuid import UUID

from stock_research_core.application.exceptions import StockResearchError, TradeRejectedError
from stock_research_core.application.virtual_portfolio.execution import (
    AverageCostPortfolioAccountingPolicy,
    NextAvailableOpenExecutionPolicy,
)
from stock_research_core.application.virtual_portfolio.feedback import RuleBasedPortfolioFeedbackPolicy
from stock_research_core.application.virtual_portfolio.service import VirtualPortfolioService
from stock_research_core.application.virtual_portfolio.valuation_service import PortfolioValuationService
from stock_research_core.domain.virtual_portfolio.enums import (
    DecisionConfidence,
    PortfolioDecisionAction,
    PortfolioTransactionType,
)
from stock_research_core.domain.virtual_portfolio.models import PortfolioDecisionJournalEntry
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from stock_research_core.infrastructure.virtual_portfolio.pandas_portfolio_analytics import (
    PandasPortfolioAnalytics,
)


def _parse_date(raw: str, label: str) -> datetime:
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise SystemExit(f"error: '{raw}' is not a valid date for {label} (expected YYYY-MM-DD)")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stock_research_core.cli.virtual_portfolio",
        description="Manage FinQuest virtual portfolios: creation, trades, decision journal, and valuation.",
    )
    parser.add_argument("--learner-id", metavar="UUID", default=None, help="Target learner ID")
    parser.add_argument("--portfolio-id", metavar="UUID", default=None, help="Target portfolio ID")

    parser.add_argument("--create", action="store_true", help="Create a new virtual portfolio")
    parser.add_argument("--name", default="Learning Portfolio", help="Portfolio name for --create")
    parser.add_argument("--initial-cash", type=float, default=10_000.0, help="Initial simulated cash")
    parser.add_argument("--start-date", default=None, help="Simulation start date (YYYY-MM-DD)")
    parser.add_argument("--benchmark", default=None, help="Benchmark ticker (must already be stored)")
    parser.add_argument(
        "--no-fractional-shares", dest="allow_fractional_shares", action="store_false", default=True
    )
    parser.add_argument(
        "--no-decision-journal", dest="require_decision_journal", action="store_false", default=True
    )

    parser.add_argument("--overview", action="store_true", help="Print a portfolio overview")

    parser.add_argument("--preview-buy", metavar="TICKER", default=None, help="Preview a buy trade")
    parser.add_argument("--preview-sell", metavar="TICKER", default=None, help="Preview a sell trade")
    parser.add_argument("--buy", metavar="TICKER", default=None, help="Execute a buy trade")
    parser.add_argument("--sell", metavar="TICKER", default=None, help="Execute a sell trade")
    parser.add_argument("--quantity", type=float, default=None, help="Trade quantity")
    parser.add_argument("--requested-at", default=None, help="Trade request date (YYYY-MM-DD)")
    parser.add_argument("--idempotency-key", default=None, help="Idempotency key for --buy/--sell")

    parser.add_argument(
        "--record-decision",
        metavar="ACTION",
        default=None,
        choices=[a.value for a in PortfolioDecisionAction if a.value in ("HOLD", "REBALANCE", "RESEARCH_MORE")],
        help="Record a non-trade decision (HOLD, REBALANCE, or RESEARCH_MORE)",
    )
    parser.add_argument("--ticker", default=None, help="Security ticker for the decision journal entry")
    parser.add_argument("--decision-at", default=None, help="Decision date for --record-decision (YYYY-MM-DD)")
    parser.add_argument(
        "--confidence",
        default="MEDIUM",
        choices=[c.value for c in DecisionConfidence],
        help="Decision confidence level",
    )
    parser.add_argument("--horizon-days", type=int, default=None, help="Expected time horizon in days")
    parser.add_argument("--rationale", default=None, help="Decision journal rationale text")
    parser.add_argument(
        "--risk-tag", dest="risk_tags", action="append", default=[], help="A documented risk (repeatable)"
    )
    parser.add_argument(
        "--information",
        dest="information_considered",
        action="append",
        default=[],
        help="Information considered (repeatable)",
    )
    parser.add_argument(
        "--assumption", dest="assumptions", action="append", default=[], help="A documented assumption (repeatable)"
    )

    parser.add_argument("--value-at", default=None, help="Value the portfolio as of this date (YYYY-MM-DD)")
    parser.add_argument("--performance", action="store_true", help="Print a performance summary")
    parser.add_argument("--start", default=None, help="Performance window start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="Performance window end date (YYYY-MM-DD)")

    return parser


def _build_portfolio_service(unit_of_work_factory) -> VirtualPortfolioService:  # noqa: ANN001
    return VirtualPortfolioService(
        unit_of_work_factory=unit_of_work_factory,
        execution_policy=NextAvailableOpenExecutionPolicy(),
        accounting_policy=AverageCostPortfolioAccountingPolicy(),
    )


def _build_valuation_service(unit_of_work_factory) -> PortfolioValuationService:  # noqa: ANN001
    return PortfolioValuationService(
        unit_of_work_factory=unit_of_work_factory,
        analytics=PandasPortfolioAnalytics(),
        feedback_policy=RuleBasedPortfolioFeedbackPolicy(),
    )


async def _create_portfolio(service: VirtualPortfolioService, args: argparse.Namespace, learner_id: UUID) -> None:
    if args.start_date is None:
        print("error: --create requires --start-date", file=sys.stderr)
        raise SystemExit(2)
    portfolio = await service.create_portfolio(
        learner_id=learner_id,
        name=args.name,
        initial_cash=args.initial_cash,
        simulation_start_at=_parse_date(args.start_date, "--start-date"),
        benchmark_ticker=args.benchmark,
        allow_fractional_shares=args.allow_fractional_shares,
        require_decision_journal=args.require_decision_journal,
    )
    print("Portfolio created:")
    print(f"  Portfolio ID:  {portfolio.portfolio_id}")
    print(f"  Name:          {portfolio.name}")
    print(f"  Initial cash:  {portfolio.initial_cash:.2f} {portfolio.base_currency}")
    print(f"  Status:        {portfolio.status.value}")


async def _print_overview(service: VirtualPortfolioService, portfolio_id: UUID) -> None:
    overview = await service.get_overview(portfolio_id)
    print("Portfolio overview:")
    print(f"  Name:          {overview.portfolio.name}")
    print(f"  Status:        {overview.portfolio.status.value}")
    print(f"  Cash balance:  {overview.portfolio.cash_balance:.2f} {overview.portfolio.base_currency}")
    print(f"  Holdings:      {len(overview.holdings)}")
    for holding in overview.holdings:
        print(f"    - security {holding.security_id}: qty={holding.quantity}, avg_cost={holding.average_cost:.2f}")
    if overview.latest_valuation is not None:
        print(f"  Latest valuation total value: {overview.latest_valuation.total_value:.2f}")
    if overview.latest_risk_assessment is not None:
        print(f"  Latest risk level: {overview.latest_risk_assessment.risk_level.value}")


async def _preview_trade(
    service: VirtualPortfolioService,
    portfolio_id: UUID,
    ticker: str,
    transaction_type: PortfolioTransactionType,
    quantity: float,
    requested_at: datetime,
) -> None:
    preview = await service.preview_trade(
        portfolio_id=portfolio_id,
        ticker=ticker,
        transaction_type=transaction_type,
        quantity=quantity,
        requested_at=requested_at,
    )
    print("Trade preview:")
    print(f"  Type:                 {transaction_type.value}")
    print(f"  Expected execution:   {preview.expected_execution_at.date()} @ {preview.expected_execution_price:.2f}")
    print(f"  Gross amount:         {preview.gross_amount:.2f}")
    print(f"  Estimated fee:        {preview.estimated_fee:.2f}")
    print(f"  Estimated cash effect:{preview.estimated_cash_effect:.2f}")
    print(f"  Cash after:           {preview.cash_after:.2f}")


async def _execute_trade(
    service: VirtualPortfolioService,
    portfolio_id: UUID,
    ticker: str,
    transaction_type: PortfolioTransactionType,
    quantity: float,
    requested_at: datetime,
    idempotency_key: str,
    args: argparse.Namespace,
) -> None:
    journal_entry = None
    if args.rationale is not None:
        journal_entry = PortfolioDecisionJournalEntry(
            portfolio_id=portfolio_id,
            learner_id=UUID(int=0),  # rewritten by the service to the portfolio's learner
            action=PortfolioDecisionAction(transaction_type.value),
            decision_at=requested_at,
            rationale=args.rationale,
            expected_horizon_days=args.horizon_days,
            confidence=DecisionConfidence(args.confidence),
            risk_tags=args.risk_tags,
            information_considered=args.information_considered,
            assumptions=args.assumptions,
        )
    result = await service.execute_trade(
        portfolio_id=portfolio_id,
        ticker=ticker,
        transaction_type=transaction_type,
        quantity=quantity,
        requested_at=requested_at,
        idempotency_key=idempotency_key,
        journal_entry=journal_entry,
    )
    print("Trade executed:")
    print(f"  Transaction ID:   {result.transaction.transaction_id}")
    print(f"  Status:           {result.transaction.status.value}")
    print(f"  Executed at:      {result.transaction.executed_at}")
    print(f"  Execution price:  {result.transaction.execution_price:.2f}")
    print(f"  Holding quantity: {result.holding.quantity}")
    print(f"  Cash balance:     {result.portfolio.cash_balance:.2f}")


async def _record_decision(
    service: VirtualPortfolioService, unit_of_work_factory, args: argparse.Namespace, portfolio_id: UUID  # noqa: ANN001
) -> None:
    from stock_research_core.application.exceptions import SecurityNotFoundError

    security_id = None
    if args.ticker is not None:
        async with unit_of_work_factory() as uow:
            security = await uow.securities.get_by_ticker(args.ticker)
        if security is None:
            raise SecurityNotFoundError(f"No stored security found for ticker '{args.ticker}'.")
        security_id = security.security_id
    if args.decision_at is None or args.rationale is None:
        print("error: --record-decision requires --decision-at and --rationale", file=sys.stderr)
        raise SystemExit(2)
    entry = await service.record_non_trade_decision(
        portfolio_id=portfolio_id,
        security_id=security_id,
        action=PortfolioDecisionAction(args.record_decision),
        decision_at=_parse_date(args.decision_at, "--decision-at"),
        rationale=args.rationale,
        expected_horizon_days=args.horizon_days,
        confidence=DecisionConfidence(args.confidence),
        risk_tags=args.risk_tags,
        information_considered=args.information_considered,
        assumptions=args.assumptions,
    )
    print("Decision recorded:")
    print(f"  Journal entry ID: {entry.journal_entry_id}")
    print(f"  Action:           {entry.action.value}")


async def _value_portfolio(valuation_service: PortfolioValuationService, portfolio_id: UUID, as_of: datetime) -> None:
    result = await valuation_service.value_portfolio(portfolio_id=portfolio_id, as_of=as_of)
    print("Portfolio valuation:")
    print(f"  Cash:                  {result.snapshot.cash_balance:.2f}")
    print(f"  Holdings value:        {result.snapshot.holdings_value:.2f}")
    print(f"  Total value:           {result.snapshot.total_value:.2f}")
    print(f"  Total return:          {result.snapshot.total_return * 100:.2f}%")
    if result.snapshot.benchmark_return is not None:
        print(f"  Benchmark return:      {result.snapshot.benchmark_return * 100:.2f}%")
        print(f"  Excess return:         {result.snapshot.excess_return * 100:.2f}%")
    print(f"  Largest position:      {result.snapshot.largest_position_weight * 100:.2f}%")
    if result.snapshot.largest_sector_weight is not None:
        print(f"  Largest sector:        {result.snapshot.largest_sector_weight * 100:.2f}%")
    print(f"  Diversification score: {result.snapshot.diversification_score:.2f}")
    print(f"  Risk level:            {result.risk_assessment.risk_level.value}")
    print(f"  Valuation version:     {result.snapshot.valuation_version}")
    print(f"  Risk policy version:   {result.risk_assessment.policy_version}")
    print("  Educational feedback:")
    for line in result.risk_assessment.educational_feedback:
        print(f"    - {line}")


async def _print_performance(
    valuation_service: PortfolioValuationService, portfolio_id: UUID, start_at: datetime, end_at: datetime
) -> None:
    summary = await valuation_service.calculate_performance(portfolio_id=portfolio_id, start_at=start_at, end_at=end_at)
    print("Performance summary:")
    print(f"  Total return:      {summary.total_return * 100:.2f}%")
    if summary.annualized_volatility is not None:
        print(f"  Annualized volatility: {summary.annualized_volatility * 100:.2f}%")
    if summary.maximum_drawdown is not None:
        print(f"  Maximum drawdown:  {summary.maximum_drawdown * 100:.2f}%")
    if summary.benchmark_return is not None:
        print(f"  Benchmark return:  {summary.benchmark_return * 100:.2f}%")
        print(f"  Excess return:     {summary.excess_return * 100:.2f}%")
    print(f"  Turnover ratio:    {summary.turnover_ratio:.2f}")
    for warning in summary.warnings:
        print(f"  Warning: {warning}")


async def _run(args: argparse.Namespace) -> int:
    settings = DatabaseSettings()
    engine = create_database_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        unit_of_work_factory = lambda: SqlAlchemyUnitOfWork(session_factory)  # noqa: E731
        service = _build_portfolio_service(unit_of_work_factory)
        valuation_service = _build_valuation_service(unit_of_work_factory)

        if args.create:
            if args.learner_id is None:
                print("error: --create requires --learner-id", file=sys.stderr)
                return 2
            await _create_portfolio(service, args, UUID(args.learner_id))
            return 0

        if args.portfolio_id is None:
            print("error: this action requires --portfolio-id", file=sys.stderr)
            return 2
        portfolio_id = UUID(args.portfolio_id)

        if args.overview:
            await _print_overview(service, portfolio_id)

        if args.preview_buy or args.preview_sell:
            ticker = args.preview_buy or args.preview_sell
            transaction_type = PortfolioTransactionType.BUY if args.preview_buy else PortfolioTransactionType.SELL
            if args.quantity is None or args.requested_at is None:
                print("error: --preview-buy/--preview-sell requires --quantity and --requested-at", file=sys.stderr)
                return 2
            await _preview_trade(
                service, portfolio_id, ticker, transaction_type, args.quantity,
                _parse_date(args.requested_at, "--requested-at"),
            )

        if args.buy or args.sell:
            ticker = args.buy or args.sell
            transaction_type = PortfolioTransactionType.BUY if args.buy else PortfolioTransactionType.SELL
            if args.quantity is None or args.requested_at is None or args.idempotency_key is None:
                print(
                    "error: --buy/--sell requires --quantity, --requested-at, and --idempotency-key",
                    file=sys.stderr,
                )
                return 2
            await _execute_trade(
                service, portfolio_id, ticker, transaction_type, args.quantity,
                _parse_date(args.requested_at, "--requested-at"), args.idempotency_key, args,
            )

        if args.record_decision:
            await _record_decision(service, unit_of_work_factory, args, portfolio_id)

        if args.value_at:
            await _value_portfolio(valuation_service, portfolio_id, _parse_date(args.value_at, "--value-at"))

        if args.performance:
            if args.start is None or args.end is None:
                print("error: --performance requires --start and --end", file=sys.stderr)
                return 2
            await _print_performance(
                valuation_service, portfolio_id,
                _parse_date(args.start, "--start"), _parse_date(args.end, "--end"),
            )

        return 0
    except TradeRejectedError as exc:
        print(f"trade rejected ({exc.reason.value}): {exc.message}", file=sys.stderr)
        return 1
    except StockResearchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
