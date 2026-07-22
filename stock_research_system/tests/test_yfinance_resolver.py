"""Offline tests for YFinanceSecurityResolver. All yfinance calls are mocked."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

import stock_research_core.infrastructure.security.yfinance_resolver as resolver_module
from stock_research_core.application.exceptions import (
    AmbiguousSecurityError,
    ProviderRequestError,
    SecurityNotFoundError,
)
from stock_research_core.domain.enums import Exchange
from stock_research_core.infrastructure.security.yfinance_resolver import (
    YFinanceSecurityResolver,
)


def _history_df(rows: int = 3) -> pd.DataFrame:
    if rows == 0:
        return pd.DataFrame()
    return pd.DataFrame(
        {"Close": [100.0] * rows},
        index=pd.date_range("2025-01-01", periods=rows, freq="D", tz="UTC"),
    )


class _FakeTicker:
    def __init__(
        self,
        info: dict[str, Any],
        history_df: pd.DataFrame | None = None,
        raise_on_history: bool = False,
    ) -> None:
        self._info = info
        self._history_df = history_df if history_df is not None else _history_df()
        self._raise_on_history = raise_on_history

    @property
    def info(self) -> dict[str, Any]:
        return self._info

    def history(self, period: str = "5d") -> pd.DataFrame:
        if self._raise_on_history:
            raise RuntimeError("provider outage")
        return self._history_df


class _FakeSearchResult:
    def __init__(self, quotes: list[dict[str, Any]]) -> None:
        self.quotes = quotes


def _install_ticker_map(monkeypatch, tickers: dict[str, _FakeTicker]) -> None:
    def _fake_ticker_constructor(symbol: str) -> _FakeTicker:
        return tickers.get(symbol, _FakeTicker(info={}, history_df=_history_df(0)))

    monkeypatch.setattr(resolver_module.yf, "Ticker", _fake_ticker_constructor)


async def test_lowercase_ticker_is_normalized_to_uppercase(monkeypatch):
    _install_ticker_map(
        monkeypatch,
        {"NVDA": _FakeTicker(info={"longName": "NVIDIA Corporation", "exchange": "NMS"})},
    )
    resolver = YFinanceSecurityResolver()

    security = await resolver.resolve(ticker="nvda", company_name=None)

    assert security.ticker == "NVDA"


async def test_valid_ticker_returns_security(monkeypatch):
    _install_ticker_map(
        monkeypatch,
        {
            "NVDA": _FakeTicker(
                info={
                    "longName": "NVIDIA Corporation",
                    "exchange": "NMS",
                    "currency": "usd",
                    "sector": "Technology",
                    "industry": "Semiconductors",
                }
            )
        },
    )
    resolver = YFinanceSecurityResolver()

    security = await resolver.resolve(ticker="NVDA", company_name=None)

    assert security.company_name == "NVIDIA Corporation"
    assert security.currency == "USD"
    assert security.sector == "Technology"
    assert security.industry == "Semiconductors"


@pytest.mark.parametrize(
    ("raw_exchange", "expected"),
    [
        ("NMS", Exchange.NASDAQ),
        ("NASDAQ", Exchange.NASDAQ),
        ("NYQ", Exchange.NYSE),
        ("NYSE", Exchange.NYSE),
        ("ASE", Exchange.AMEX),
        ("AMEX", Exchange.AMEX),
        ("XETRA", Exchange.OTHER),
    ],
)
async def test_exchange_mapping(monkeypatch, raw_exchange, expected):
    _install_ticker_map(
        monkeypatch,
        {"AAA": _FakeTicker(info={"longName": "Example Corp", "exchange": raw_exchange})},
    )
    resolver = YFinanceSecurityResolver()

    security = await resolver.resolve(ticker="AAA", company_name=None)

    assert security.exchange == expected


async def test_missing_sector_and_industry_do_not_fail(monkeypatch):
    _install_ticker_map(
        monkeypatch,
        {"AAA": _FakeTicker(info={"longName": "Example Corp", "exchange": "NMS"})},
    )
    resolver = YFinanceSecurityResolver()

    security = await resolver.resolve(ticker="AAA", company_name=None)

    assert security.sector is None
    assert security.industry is None


async def test_company_name_fallback_order(monkeypatch):
    _install_ticker_map(
        monkeypatch,
        {
            "LONG": _FakeTicker(
                info={"longName": "Long Name Co", "shortName": "Short", "exchange": "NMS"}
            ),
            "SHORT": _FakeTicker(info={"shortName": "Short Only Co", "exchange": "NMS"}),
            "NONE": _FakeTicker(info={"exchange": "NMS"}),
        },
    )
    resolver = YFinanceSecurityResolver()

    long_result = await resolver.resolve(ticker="LONG", company_name=None)
    short_result = await resolver.resolve(ticker="SHORT", company_name=None)
    none_result = await resolver.resolve(ticker="NONE", company_name=None)

    assert long_result.company_name == "Long Name Co"
    assert short_result.company_name == "Short Only Co"
    assert none_result.company_name == "NONE"


async def test_invalid_ticker_with_no_history_raises_security_not_found(monkeypatch):
    _install_ticker_map(
        monkeypatch,
        {"ZZZZ": _FakeTicker(info={"longName": "Nothing"}, history_df=_history_df(0))},
    )
    resolver = YFinanceSecurityResolver()

    with pytest.raises(SecurityNotFoundError):
        await resolver.resolve(ticker="ZZZZ", company_name=None)


async def test_company_name_resolution_chooses_exact_equity_match(monkeypatch):
    _install_ticker_map(
        monkeypatch,
        {"NVDA": _FakeTicker(info={"longName": "NVIDIA Corporation", "exchange": "NMS"})},
    )

    def _fake_search(query: str, max_results: int = 10) -> _FakeSearchResult:
        return _FakeSearchResult(
            quotes=[
                {
                    "symbol": "NVDA",
                    "longname": "NVIDIA Corporation",
                    "quoteType": "EQUITY",
                    "exchange": "NMS",
                },
                {
                    "symbol": "NVDX",
                    "longname": "Some Leveraged NVDA ETN",
                    "quoteType": "EQUITY",
                    "exchange": "NMS",
                },
            ]
        )

    monkeypatch.setattr(resolver_module.yf, "Search", _fake_search)
    resolver = YFinanceSecurityResolver()

    security = await resolver.resolve(ticker=None, company_name="NVIDIA Corporation")

    assert security.ticker == "NVDA"


async def test_no_company_result_raises_security_not_found(monkeypatch):
    def _fake_search(query: str, max_results: int = 10) -> _FakeSearchResult:
        return _FakeSearchResult(quotes=[{"symbol": "BTC-USD", "quoteType": "CRYPTOCURRENCY"}])

    monkeypatch.setattr(resolver_module.yf, "Search", _fake_search)
    resolver = YFinanceSecurityResolver()

    with pytest.raises(SecurityNotFoundError):
        await resolver.resolve(ticker=None, company_name="Nonexistent Company")


async def test_ambiguous_company_results_raise_ambiguous_security_error(monkeypatch):
    def _fake_search(query: str, max_results: int = 10) -> _FakeSearchResult:
        return _FakeSearchResult(
            quotes=[
                {
                    "symbol": "AAA",
                    "longname": "Example Holdings",
                    "quoteType": "EQUITY",
                    "exchange": "NMS",
                },
                {
                    "symbol": "BBB",
                    "longname": "Example Holdings",
                    "quoteType": "EQUITY",
                    "exchange": "NYQ",
                },
            ]
        )

    monkeypatch.setattr(resolver_module.yf, "Search", _fake_search)
    resolver = YFinanceSecurityResolver()

    with pytest.raises(AmbiguousSecurityError):
        await resolver.resolve(ticker=None, company_name="Example Holdings")


async def test_provider_exception_becomes_provider_request_error(monkeypatch):
    _install_ticker_map(
        monkeypatch,
        {"NVDA": _FakeTicker(info={"longName": "NVIDIA Corporation"}, raise_on_history=True)},
    )
    resolver = YFinanceSecurityResolver()

    with pytest.raises(ProviderRequestError):
        await resolver.resolve(ticker="NVDA", company_name=None)
