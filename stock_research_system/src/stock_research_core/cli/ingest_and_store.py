"""CLI for ingesting market data and persisting it to the database.

Historical (PowerShell):

    python -m stock_research_core.cli.ingest_and_store `
      --ticker NVDA `
      --start 2025-01-01 `
      --end 2025-02-01

Company name:

    python -m stock_research_core.cli.ingest_and_store `
      --company-name "NVIDIA Corporation" `
      --start 2025-01-01 `
      --end 2025-02-01

Incremental:

    python -m stock_research_core.cli.ingest_and_store `
      --ticker NVDA `
      --incremental `
      --end 2025-03-01

Benchmark:

    python -m stock_research_core.cli.ingest_and_store `
      --benchmark SPY `
      --start 2025-01-01 `
      --end 2025-02-01

This module is a composition root: it is the one place outside the
infrastructure layer allowed to import concrete adapters directly.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone

from stock_research_core.application.exceptions import StockResearchError
from stock_research_core.application.market_data.service import MarketDataIngestionService
from stock_research_core.application.persistence.models import PersistedMarketDataResult
from stock_research_core.application.persistence.service import (
    PersistedMarketDataIngestionService,
)
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from stock_research_core.infrastructure.market_data.yfinance_adapter import (
    YFinanceMarketDataAdapter,
)
from stock_research_core.infrastructure.security.yfinance_resolver import (
    YFinanceSecurityResolver,
)


def _parse_utc_date(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"'{value}' is not a valid YYYY-MM-DD date.") from exc
    return parsed.replace(tzinfo=timezone.utc)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stock_research_core.cli.ingest_and_store",
        description="Ingest market data (yfinance) and persist it to PostgreSQL/TimescaleDB.",
    )
    parser.add_argument("--ticker", default=None, help="Ticker symbol, e.g. NVDA")
    parser.add_argument(
        "--company-name", default=None, help="Company name, e.g. 'NVIDIA Corporation'"
    )
    parser.add_argument("--benchmark", default=None, help="Benchmark ticker, e.g. SPY")
    parser.add_argument(
        "--start", default=None, type=_parse_utc_date, help="Start date (YYYY-MM-DD), UTC"
    )
    parser.add_argument(
        "--end", required=True, type=_parse_utc_date, help="End date (YYYY-MM-DD), UTC"
    )
    parser.add_argument(
        "--interval", default="1d", help="Bar interval (only '1d' is supported in this MVP)"
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Fetch only bars after the last stored bar for --ticker",
    )
    parser.add_argument(
        "--no-track",
        action="store_true",
        help="Do not create/update a TrackedSecurity row for this security",
    )
    return parser


def _validate_mode(args: argparse.Namespace) -> None:
    if args.benchmark:
        if args.ticker or args.company_name or args.incremental:
            raise ValueError(
                "--benchmark cannot be combined with --ticker, --company-name, or --incremental."
            )
        if args.start is None:
            raise ValueError("Benchmark mode requires --start and --end.")
    elif args.incremental:
        if not args.ticker:
            raise ValueError("Incremental mode requires --ticker.")
        if args.company_name:
            raise ValueError("Incremental mode does not accept --company-name.")
    else:
        if not args.ticker and not args.company_name:
            raise ValueError("Historical mode requires --ticker or --company-name.")
        if args.start is None:
            raise ValueError("Historical mode requires --start and --end.")


def _print_result(result: PersistedMarketDataResult, *, is_tracked: bool) -> None:
    ingestion_result = result.ingestion_result
    security = ingestion_result.security
    counts = result.persistence_counts

    print(f"Security ID (canonical): {security.security_id}")
    print(f"Ticker:                  {security.ticker}")
    print(f"Company name:            {security.company_name}")
    print(f"Provider bars:           {counts.bars_attempted}")
    print(f"Persisted bars:          {counts.bars_persisted}")
    print(f"Ingestion run ID:        {result.run_id}")
    print(f"Run status:              {result.status.value}")
    print(f"First stored timestamp:  {ingestion_result.quality_report.first_bar_at}")
    print(f"Last stored timestamp:   {result.latest_stored_bar_at}")

    if ingestion_result.quality_report.issues:
        print("Quality issues:")
        for issue in ingestion_result.quality_report.issues:
            print(f"  [{issue.severity}] {issue.code}: {issue.message}")
    else:
        print("Quality issues: none")

    print(f"Tracked security:        {'yes' if is_tracked else 'no'}")


async def _run(args: argparse.Namespace) -> int:
    try:
        _validate_mode(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    settings = DatabaseSettings()
    engine = create_database_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        market_data_service = MarketDataIngestionService(
            security_resolver=YFinanceSecurityResolver(),
            market_data_provider=YFinanceMarketDataAdapter(),
        )
        persistence_service = PersistedMarketDataIngestionService(
            market_data_ingestion_service=market_data_service,
            unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(session_factory),
        )

        track_security = not args.no_track

        if args.benchmark:
            result = await persistence_service.ingest_benchmark_and_store(
                benchmark_ticker=args.benchmark,
                start_at=args.start,
                end_at=args.end,
                interval=args.interval,
                track_security=track_security,
            )
        elif args.incremental:
            result = await persistence_service.ingest_incremental_and_store(
                ticker=args.ticker,
                end_at=args.end,
                interval=args.interval,
            )
        else:
            result = await persistence_service.ingest_historical_and_store(
                ticker=args.ticker,
                company_name=args.company_name,
                start_at=args.start,
                end_at=args.end,
                interval=args.interval,
                track_security=track_security,
            )

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            tracked = await uow.tracked_securities.get(result.ingestion_result.security.security_id)
        is_tracked = tracked is not None

        _print_result(result, is_tracked=is_tracked)
        return 0
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
