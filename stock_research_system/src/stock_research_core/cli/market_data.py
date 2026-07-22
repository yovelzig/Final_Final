"""Manual CLI for exercising security resolution and market-data ingestion.

Example (PowerShell):

    python -m stock_research_core.cli.market_data `
      --ticker NVDA `
      --start 2025-01-01 `
      --end 2025-02-01

    python -m stock_research_core.cli.market_data `
      --company-name "NVIDIA Corporation" `
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
from stock_research_core.application.market_data.models import MarketDataIngestionResult
from stock_research_core.application.market_data.service import MarketDataIngestionService
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
        prog="python -m stock_research_core.cli.market_data",
        description="Manually resolve a security and fetch its historical market data.",
    )
    parser.add_argument("--ticker", default=None, help="Ticker symbol, e.g. NVDA")
    parser.add_argument(
        "--company-name", default=None, help="Company name, e.g. 'NVIDIA Corporation'"
    )
    parser.add_argument(
        "--start", required=True, type=_parse_utc_date, help="Start date (YYYY-MM-DD), UTC"
    )
    parser.add_argument(
        "--end", required=True, type=_parse_utc_date, help="End date (YYYY-MM-DD), UTC"
    )
    parser.add_argument(
        "--interval", default="1d", help="Bar interval (only '1d' is supported in this MVP)"
    )
    parser.add_argument(
        "--limit", type=int, default=10, help="Maximum number of bars to print (default: 10)"
    )
    return parser


def _print_result(result: MarketDataIngestionResult, limit: int) -> None:
    security = result.security
    bars = result.bars
    report = result.quality_report

    print(f"Ticker:        {security.ticker}")
    print(f"Company name:  {security.company_name}")
    print(f"Exchange:      {security.exchange.value}")
    print(f"Provider:      {result.provider_name}")
    print(f"Bars returned: {len(bars)}")
    print(f"First bar at:  {report.first_bar_at}")
    print(f"Last bar at:   {report.last_bar_at}")

    if report.issues:
        print("Quality issues:")
        for issue in report.issues:
            print(f"  [{issue.severity}] {issue.code}: {issue.message}")
    else:
        print("Quality issues: none")

    shown = bars[: max(limit, 0)]
    print(f"First {len(shown)} bar(s):")
    for bar in shown:
        print(
            f"  {bar.timestamp.date()}  "
            f"O={bar.open:.2f} H={bar.high:.2f} L={bar.low:.2f} C={bar.close:.2f} "
            f"AdjC={bar.adjusted_close:.2f} V={bar.volume}"
        )


async def _run(args: argparse.Namespace) -> int:
    if not args.ticker and not args.company_name:
        print("error: either --ticker or --company-name is required", file=sys.stderr)
        return 2

    service = MarketDataIngestionService(
        security_resolver=YFinanceSecurityResolver(),
        market_data_provider=YFinanceMarketDataAdapter(),
    )

    try:
        result = await service.ingest_historical(
            ticker=args.ticker,
            company_name=args.company_name,
            start_at=args.start,
            end_at=args.end,
            interval=args.interval,
        )
    except StockResearchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _print_result(result, limit=args.limit)
    return 0


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
