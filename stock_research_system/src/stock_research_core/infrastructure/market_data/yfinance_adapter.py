"""yfinance-backed implementation of `MarketDataPort`.

This module is the only place allowed to hold a pandas DataFrame. Every
public method returns domain objects (`MarketBar`) plus an application
result model (`MarketDataQualityReport`); no raw DataFrame ever leaves
this module.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import yfinance as yf
from pydantic import ValidationError

from stock_research_core.application.exceptions import (
    InvalidMarketDataError,
    MarketDataUnavailableError,
    ProviderRequestError,
    UnsupportedIntervalError,
)
from stock_research_core.application.market_data.models import (
    DataQualityIssue,
    MarketDataQualityReport,
)
from stock_research_core.domain.models import MarketBar, Security

_SUPPORTED_INTERVAL = "1d"
_PROVIDER_NAME = "yfinance"
_KNOWN_FIELDS = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
_REQUIRED_FIELDS = {"Open", "High", "Low", "Close"}
_END_DATE_GAP_TOLERANCE = timedelta(days=5)
_CALENDAR_GAP_THRESHOLD = timedelta(days=7)


class YFinanceMarketDataAdapter:
    """Fetches and normalizes OHLCV bars from yfinance into `MarketBar` objects."""

    provider_name = _PROVIDER_NAME

    async def fetch_bars(
        self,
        security: Security,
        start_at: datetime,
        end_at: datetime,
        interval: str = "1d",
    ) -> list[MarketBar]:
        bars, _ = await self.fetch_bars_with_report(security, start_at, end_at, interval)
        return bars

    async def fetch_bars_with_report(
        self,
        security: Security,
        start_at: datetime,
        end_at: datetime,
        interval: str = "1d",
    ) -> tuple[list[MarketBar], MarketDataQualityReport]:
        if interval != _SUPPORTED_INTERVAL:
            raise UnsupportedIntervalError(
                f"Interval '{interval}' is not supported yet; only "
                f"'{_SUPPORTED_INTERVAL}' is available in this MVP."
            )
        if start_at.tzinfo is None or end_at.tzinfo is None:
            raise ValueError("start_at and end_at must be timezone-aware datetimes.")
        if start_at >= end_at:
            raise ValueError("start_at must be earlier than end_at.")

        start_utc = start_at.astimezone(timezone.utc)
        end_utc = end_at.astimezone(timezone.utc)
        # yfinance treats `end` as exclusive; pad by one day so the
        # user-requested end date can be included, then filter back down.
        provider_end = end_utc + timedelta(days=1)

        raw_df = await self._download(security.ticker, start_utc, provider_end)
        provider_rows_received = int(len(raw_df))

        if raw_df.empty:
            raise MarketDataUnavailableError(
                f"yfinance returned no market data for '{security.ticker}' between "
                f"{start_utc.date()} and {end_utc.date()}."
            )

        df = _normalize_columns(raw_df, security.ticker)

        missing_columns = _REQUIRED_FIELDS - set(df.columns)
        if missing_columns:
            raise InvalidMarketDataError(
                f"yfinance response for '{security.ticker}' is missing required "
                f"columns: {sorted(missing_columns)}."
            )

        issues: list[DataQualityIssue] = []
        has_adjusted_close = "Adj Close" in df.columns
        has_volume = "Volume" in df.columns

        if not has_adjusted_close:
            issues.append(
                DataQualityIssue(
                    code="ADJUSTED_CLOSE_UNAVAILABLE",
                    message="Provider did not return an adjusted close column; using close instead.",
                    severity="WARNING",
                )
            )
        if not has_volume:
            issues.append(
                DataQualityIssue(
                    code="VOLUME_UNAVAILABLE",
                    message="Provider did not return a volume column; using zero instead.",
                    severity="WARNING",
                )
            )

        df = df.sort_index()

        before_dedup = len(df)
        df = df[~df.index.duplicated(keep="first")]
        duplicate_rows_removed = before_dedup - len(df)

        before_dropna = len(df)
        df = df.dropna(subset=list(_REQUIRED_FIELDS))
        missing_essential_removed = before_dropna - len(df)

        bars: list[MarketBar] = []
        validation_failures = 0
        missing_volume_rows = 0

        for index, row in df.iterrows():
            timestamp = _to_utc_datetime(index)

            if has_adjusted_close and pd.notna(row["Adj Close"]):
                adjusted_close = row["Adj Close"]
            else:
                adjusted_close = row["Close"]

            if has_volume:
                if pd.isna(row["Volume"]):
                    volume = 0
                    missing_volume_rows += 1
                else:
                    volume = max(int(row["Volume"]), 0)
            else:
                volume = 0

            try:
                bar = MarketBar(
                    security_id=security.security_id,
                    timestamp=timestamp,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    adjusted_close=float(adjusted_close),
                    volume=volume,
                    interval=_SUPPORTED_INTERVAL,
                    source_name=_PROVIDER_NAME,
                )
            except ValidationError:
                validation_failures += 1
                continue
            bars.append(bar)

        bars = sorted(
            (bar for bar in bars if start_utc <= bar.timestamp <= end_utc),
            key=lambda bar: bar.timestamp,
        )

        invalid_rows_removed = missing_essential_removed + validation_failures

        if has_volume and missing_volume_rows:
            issues.append(
                DataQualityIssue(
                    code="VOLUME_MISSING_ROWS",
                    message=f"{missing_volume_rows} row(s) had a missing volume value; treated as zero.",
                    severity="WARNING",
                )
            )
        if duplicate_rows_removed:
            issues.append(
                DataQualityIssue(
                    code="DUPLICATE_ROWS_REMOVED",
                    message=f"{duplicate_rows_removed} duplicate timestamp row(s) were removed.",
                    severity="WARNING",
                )
            )
        if invalid_rows_removed:
            issues.append(
                DataQualityIssue(
                    code="INVALID_ROWS_REMOVED",
                    message=f"{invalid_rows_removed} row(s) were removed for missing or invalid OHLC data.",
                    severity="WARNING",
                )
            )

        if not bars:
            raise MarketDataUnavailableError(
                f"No valid market data bars remained for '{security.ticker}' after quality filtering."
            )

        first_bar_at = bars[0].timestamp
        last_bar_at = bars[-1].timestamp

        if end_utc - last_bar_at > _END_DATE_GAP_TOLERANCE:
            issues.append(
                DataQualityIssue(
                    code="NO_BAR_NEAR_END_DATE",
                    message=(
                        f"The last available bar ({last_bar_at.date()}) is more than "
                        f"{_END_DATE_GAP_TOLERANCE.days} days before the requested end "
                        f"date ({end_utc.date()})."
                    ),
                    severity="WARNING",
                    timestamp=last_bar_at,
                )
            )

        for previous_bar, current_bar in zip(bars, bars[1:]):
            gap = current_bar.timestamp - previous_bar.timestamp
            if gap > _CALENDAR_GAP_THRESHOLD:
                issues.append(
                    DataQualityIssue(
                        code="CALENDAR_GAP",
                        message=(
                            f"A {gap.days}-day gap was found between "
                            f"{previous_bar.timestamp.date()} and {current_bar.timestamp.date()}."
                        ),
                        severity="WARNING",
                        timestamp=current_bar.timestamp,
                    )
                )

        report = MarketDataQualityReport(
            requested_start_at=start_utc,
            requested_end_at=end_utc,
            first_bar_at=first_bar_at,
            last_bar_at=last_bar_at,
            provider_rows_received=provider_rows_received,
            valid_bars_returned=len(bars),
            duplicate_rows_removed=duplicate_rows_removed,
            invalid_rows_removed=invalid_rows_removed,
            issues=issues,
        )

        return bars, report

    async def _download(self, ticker: str, start_at: datetime, end_at: datetime) -> pd.DataFrame:
        try:
            return await asyncio.to_thread(self._download_sync, ticker, start_at, end_at)
        except Exception as exc:  # noqa: BLE001 - isolate provider failures
            raise ProviderRequestError(
                f"yfinance request failed while fetching bars for '{ticker}'."
            ) from exc

    @staticmethod
    def _download_sync(ticker: str, start_at: datetime, end_at: datetime) -> pd.DataFrame:
        return yf.Ticker(ticker).history(
            start=start_at,
            end=end_at,
            interval=_SUPPORTED_INTERVAL,
            auto_adjust=False,
        )


def _normalize_columns(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Flatten MultiIndex/ticker-prefixed provider columns to plain OHLCV names."""
    df = df.copy()

    if isinstance(df.columns, pd.MultiIndex):
        new_columns = []
        for col in df.columns:
            parts = [str(part) for part in col if part not in (None, "")]
            match = next((part for part in parts if part in _KNOWN_FIELDS), None)
            new_columns.append(match or " ".join(parts))
        df.columns = new_columns
    else:
        df.columns = [str(col) for col in df.columns]

    renamed: dict[str, str] = {}
    for col in df.columns:
        if col in _KNOWN_FIELDS:
            continue
        for field in _KNOWN_FIELDS:
            if col == f"{ticker} {field}" or col.endswith(f" {field}"):
                renamed[col] = field
                break
    if renamed:
        df = df.rename(columns=renamed)

    return df


def _to_utc_datetime(index_value: Any) -> datetime:
    timestamp = pd.Timestamp(index_value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(timezone.utc)
    else:
        timestamp = timestamp.tz_convert(timezone.utc)
    return timestamp.to_pydatetime()
