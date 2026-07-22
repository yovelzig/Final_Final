"""Offline tests for YFinanceMarketDataAdapter. All yfinance calls are mocked."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import stock_research_core.infrastructure.market_data.yfinance_adapter as adapter_module
from stock_research_core.application.exceptions import (
    MarketDataUnavailableError,
    ProviderRequestError,
    UnsupportedIntervalError,
)
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.models import Security
from stock_research_core.infrastructure.market_data.yfinance_adapter import (
    YFinanceMarketDataAdapter,
)

START_AT = datetime(2025, 1, 1, tzinfo=timezone.utc)
END_AT = datetime(2025, 1, 10, tzinfo=timezone.utc)


def _security() -> Security:
    return Security(ticker="NVDA", company_name="NVIDIA Corporation", exchange=Exchange.NASDAQ)


def _valid_frame() -> pd.DataFrame:
    index = pd.date_range("2025-01-02", periods=5, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "High": [105.0, 106.0, 107.0, 108.0, 109.0],
            "Low": [95.0, 96.0, 97.0, 98.0, 99.0],
            "Close": [102.0, 103.0, 104.0, 105.0, 106.0],
            "Adj Close": [101.5, 102.5, 103.5, 104.5, 105.5],
            "Volume": [1000, 1100, 1200, 1300, 1400],
        },
        index=index,
    )


class _FakeTicker:
    def __init__(self, history_df: pd.DataFrame, raise_error: bool = False) -> None:
        self._history_df = history_df
        self._raise_error = raise_error

    def history(self, start=None, end=None, interval="1d", auto_adjust=False) -> pd.DataFrame:
        if self._raise_error:
            raise RuntimeError("provider outage")
        return self._history_df


def _install_ticker(monkeypatch, history_df: pd.DataFrame, raise_error: bool = False) -> None:
    fake = _FakeTicker(history_df, raise_error=raise_error)
    monkeypatch.setattr(adapter_module.yf, "Ticker", lambda symbol: fake)


def _install_failing_ticker(monkeypatch) -> None:
    def _fail(symbol: str):
        raise AssertionError("the provider must not be called for this test")

    monkeypatch.setattr(adapter_module.yf, "Ticker", _fail)


async def test_normal_dataframe_becomes_sorted_market_bars(monkeypatch):
    frame = _valid_frame().iloc[::-1]  # unsorted on purpose
    _install_ticker(monkeypatch, frame)
    adapter = YFinanceMarketDataAdapter()

    bars = await adapter.fetch_bars(_security(), START_AT, END_AT)

    assert len(bars) == 5
    timestamps = [bar.timestamp for bar in bars]
    assert timestamps == sorted(timestamps)


async def test_security_id_is_preserved(monkeypatch):
    _install_ticker(monkeypatch, _valid_frame())
    adapter = YFinanceMarketDataAdapter()
    security = _security()

    bars = await adapter.fetch_bars(security, START_AT, END_AT)

    assert bars
    assert all(bar.security_id == security.security_id for bar in bars)


async def test_timestamps_become_timezone_aware_utc(monkeypatch):
    frame = _valid_frame().iloc[:3].copy()
    frame.index = pd.date_range("2025-01-02", periods=3, freq="D")  # tz-naive
    _install_ticker(monkeypatch, frame)
    adapter = YFinanceMarketDataAdapter()

    bars = await adapter.fetch_bars(_security(), START_AT, END_AT)

    assert bars
    assert all(bar.timestamp.tzinfo is not None for bar in bars)
    assert all(bar.timestamp.utcoffset() == timedelta(0) for bar in bars)


async def test_duplicate_timestamps_are_removed(monkeypatch):
    frame = _valid_frame()
    duplicated_row = frame.iloc[[0]]
    frame_with_duplicate = pd.concat([frame, duplicated_row])
    _install_ticker(monkeypatch, frame_with_duplicate)
    adapter = YFinanceMarketDataAdapter()

    bars, report = await adapter.fetch_bars_with_report(_security(), START_AT, END_AT)

    assert len(bars) == 5
    assert report.duplicate_rows_removed == 1


async def test_invalid_rows_are_removed_and_reported(monkeypatch):
    frame = _valid_frame()
    frame.loc[frame.index[2], "High"] = 50.0  # High below Close/Open -> invalid OHLC
    _install_ticker(monkeypatch, frame)
    adapter = YFinanceMarketDataAdapter()

    bars, report = await adapter.fetch_bars_with_report(_security(), START_AT, END_AT)

    assert len(bars) == 4
    assert report.invalid_rows_removed == 1


async def test_missing_adjusted_close_falls_back_to_close(monkeypatch):
    frame = _valid_frame().drop(columns=["Adj Close"])
    _install_ticker(monkeypatch, frame)
    adapter = YFinanceMarketDataAdapter()

    bars, report = await adapter.fetch_bars_with_report(_security(), START_AT, END_AT)

    assert bars
    assert all(bar.adjusted_close == bar.close for bar in bars)
    assert any(issue.code == "ADJUSTED_CLOSE_UNAVAILABLE" for issue in report.issues)


async def test_missing_volume_becomes_zero(monkeypatch):
    frame = _valid_frame().drop(columns=["Volume"])
    _install_ticker(monkeypatch, frame)
    adapter = YFinanceMarketDataAdapter()

    bars, report = await adapter.fetch_bars_with_report(_security(), START_AT, END_AT)

    assert bars
    assert all(bar.volume == 0 for bar in bars)
    assert any(issue.code == "VOLUME_UNAVAILABLE" for issue in report.issues)


async def test_empty_historical_response_raises_market_data_unavailable(monkeypatch):
    _install_ticker(monkeypatch, pd.DataFrame())
    adapter = YFinanceMarketDataAdapter()

    with pytest.raises(MarketDataUnavailableError):
        await adapter.fetch_bars(_security(), START_AT, END_AT)


async def test_unsupported_interval_raises_unsupported_interval_error(monkeypatch):
    _install_failing_ticker(monkeypatch)
    adapter = YFinanceMarketDataAdapter()

    with pytest.raises(UnsupportedIntervalError):
        await adapter.fetch_bars(_security(), START_AT, END_AT, interval="1h")


async def test_naive_timestamps_are_rejected(monkeypatch):
    _install_failing_ticker(monkeypatch)
    adapter = YFinanceMarketDataAdapter()

    with pytest.raises(ValueError):
        await adapter.fetch_bars(_security(), datetime(2025, 1, 1), END_AT)


async def test_start_after_end_is_rejected(monkeypatch):
    _install_failing_ticker(monkeypatch)
    adapter = YFinanceMarketDataAdapter()

    with pytest.raises(ValueError):
        await adapter.fetch_bars(_security(), END_AT, START_AT)


async def test_multiindex_columns_are_handled(monkeypatch):
    frame = _valid_frame()
    frame.columns = pd.MultiIndex.from_tuples([(col, "NVDA") for col in frame.columns])
    _install_ticker(monkeypatch, frame)
    adapter = YFinanceMarketDataAdapter()

    bars = await adapter.fetch_bars(_security(), START_AT, END_AT)

    assert len(bars) == 5


async def test_provider_failure_becomes_provider_request_error(monkeypatch):
    _install_ticker(monkeypatch, _valid_frame(), raise_error=True)
    adapter = YFinanceMarketDataAdapter()

    with pytest.raises(ProviderRequestError):
        await adapter.fetch_bars(_security(), START_AT, END_AT)


async def test_ohlc_invalid_rows_do_not_enter_result(monkeypatch):
    frame = _valid_frame()
    bad_timestamp = frame.index[1]
    frame.loc[bad_timestamp, "Low"] = 1000.0  # Low above High -> invalid OHLC
    _install_ticker(monkeypatch, frame)
    adapter = YFinanceMarketDataAdapter()

    bars = await adapter.fetch_bars(_security(), START_AT, END_AT)

    bad_utc_timestamp = bad_timestamp.to_pydatetime().astimezone(timezone.utc)
    assert bad_utc_timestamp not in [bar.timestamp for bar in bars]
    assert len(bars) == 4
