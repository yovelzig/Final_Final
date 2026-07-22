"""Pandas/NumPy-backed implementation of `ScenarioCalculatorPort`.

All pandas/NumPy usage is confined to this module (infrastructure only
- domain and application `market_scenarios` packages never import
either). Every synchronous calculation runs in a worker thread via
`asyncio.to_thread` so it never blocks the event loop. Public methods
only ever return domain objects - a `pandas.DataFrame` never leaves
this module.
"""

from __future__ import annotations

import asyncio
import math

import numpy as np
import pandas as pd

from stock_research_core.application.exceptions import InsufficientScenarioDataError
from stock_research_core.application.market_scenarios.calculator import (
    OBSERVATION_CALCULATION_VERSION,
    OUTCOME_CALCULATION_VERSION,
    classify_outcome_direction,
)
from stock_research_core.domain.market_scenarios.enums import ScenarioOutcomeDirection
from stock_research_core.domain.market_scenarios.models import (
    HistoricalMarketScenario,
    ScenarioObservationMetrics,
    ScenarioOutcome,
)
from stock_research_core.domain.models import MarketBar

_TRADING_DAYS_PER_YEAR = 252
_MINIMUM_BARS_FOR_VOLATILITY = 3
_BAR_COLUMNS = ["timestamp", "open", "high", "low", "close", "adjusted_close", "volume"]


def _prepare_frame(bars: list[MarketBar]) -> tuple[pd.DataFrame, list[str]]:
    """Sort ascending; deduplicate timestamps deterministically (keep the
    latest occurrence, matching how a database upsert resolves the same
    conflict) and return a warning describing what happened, if
    anything.
    """
    if not bars:
        return pd.DataFrame(columns=_BAR_COLUMNS), []

    frame = pd.DataFrame(
        [
            {
                "timestamp": bar.timestamp,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "adjusted_close": bar.adjusted_close,
                "volume": bar.volume,
            }
            for bar in bars
        ]
    ).sort_values("timestamp", kind="stable")

    warnings: list[str] = []
    duplicate_count = int(frame["timestamp"].duplicated(keep="last").sum())
    if duplicate_count > 0:
        frame = frame.drop_duplicates(subset="timestamp", keep="last")
        warnings.append(
            f"{duplicate_count} duplicate bar timestamp(s) were found and resolved "
            "deterministically by keeping the latest one."
        )
    return frame.reset_index(drop=True), warnings


def _build_outcome_summary(focal_return: float, direction: ScenarioOutcomeDirection) -> str:
    percentage = focal_return * 100.0
    if direction == ScenarioOutcomeDirection.POSITIVE:
        return (
            f"The focal security rose {percentage:.2f}% from the decision point to the end of "
            "the reveal window."
        )
    if direction == ScenarioOutcomeDirection.NEGATIVE:
        return (
            f"The focal security fell {abs(percentage):.2f}% from the decision point to the end "
            "of the reveal window."
        )
    return (
        f"The focal security moved {percentage:.2f}% from the decision point to the end of the "
        "reveal window - close to flat."
    )


class PandasScenarioCalculator:
    """scenario-observation-v1 / scenario-outcome-v1: deterministic,
    point-in-time-safe scenario calculations backed by pandas/NumPy.
    """

    async def calculate_observation(
        self,
        *,
        scenario: HistoricalMarketScenario,
        focal_bars: list[MarketBar],
        benchmark_bars: list[MarketBar],
    ) -> ScenarioObservationMetrics:
        return await asyncio.to_thread(
            self._calculate_observation_sync, scenario, focal_bars, benchmark_bars
        )

    async def calculate_outcome(
        self,
        *,
        scenario: HistoricalMarketScenario,
        focal_bars: list[MarketBar],
        benchmark_bars: list[MarketBar],
    ) -> ScenarioOutcome:
        return await asyncio.to_thread(self._calculate_outcome_sync, scenario, focal_bars, benchmark_bars)

    # -- observation ---------------------------------------------------------

    def _calculate_observation_sync(
        self,
        scenario: HistoricalMarketScenario,
        focal_bars: list[MarketBar],
        benchmark_bars: list[MarketBar],
    ) -> ScenarioObservationMetrics:
        window_bars = [
            bar
            for bar in focal_bars
            if scenario.observation_start_at <= bar.timestamp <= scenario.decision_at
        ]
        frame, warnings = _prepare_frame(window_bars)

        if len(frame) < scenario.minimum_observation_bars:
            raise InsufficientScenarioDataError(
                f"Only {len(frame)} observation bars are available for scenario "
                f"'{scenario.scenario_id}'; {scenario.minimum_observation_bars} are required."
            )

        data_cutoff_at = max(bar.timestamp for bar in window_bars)

        start_close = float(frame["close"].iloc[0])
        decision_close = float(frame["close"].iloc[-1])
        highest_close = float(frame["close"].max())
        lowest_close = float(frame["close"].min())
        price_change_percentage = (decision_close - start_close) / start_close * 100.0

        adjusted = frame["adjusted_close"].astype(float)
        observation_return = float(adjusted.iloc[-1] / adjusted.iloc[0] - 1.0)

        log_returns = np.log(adjusted / adjusted.shift(1)).dropna()
        if len(log_returns) >= _MINIMUM_BARS_FOR_VOLATILITY - 1:
            annualized_volatility = float(log_returns.std(ddof=1) * math.sqrt(_TRADING_DAYS_PER_YEAR))
        else:
            annualized_volatility = None
            warnings.append(
                f"Not enough bars to compute annualized volatility (need at least "
                f"{_MINIMUM_BARS_FOR_VOLATILITY})."
            )

        running_max = adjusted.cummax()
        maximum_drawdown = float(min(0.0, (adjusted / running_max - 1.0).min()))

        average_daily_volume = float(frame["volume"].astype(float).mean())

        benchmark_window_bars = [
            bar
            for bar in benchmark_bars
            if scenario.observation_start_at <= bar.timestamp <= scenario.decision_at
        ]
        benchmark_frame, benchmark_warnings = _prepare_frame(benchmark_window_bars)
        warnings.extend(benchmark_warnings)

        benchmark_observation_return = None
        excess_observation_return = None
        if len(benchmark_frame) >= 2:
            benchmark_adjusted = benchmark_frame["adjusted_close"].astype(float)
            benchmark_observation_return = float(
                benchmark_adjusted.iloc[-1] / benchmark_adjusted.iloc[0] - 1.0
            )
            excess_observation_return = observation_return - benchmark_observation_return
        elif scenario.benchmark_security_id is not None:
            warnings.append(
                "Insufficient benchmark bars in the observation window; benchmark metrics were skipped."
            )

        return ScenarioObservationMetrics(
            data_cutoff_at=data_cutoff_at,
            observation_bar_count=len(frame),
            start_close=start_close,
            decision_close=decision_close,
            observation_return=observation_return,
            annualized_volatility=annualized_volatility,
            maximum_drawdown=maximum_drawdown,
            average_daily_volume=average_daily_volume,
            benchmark_observation_return=benchmark_observation_return,
            excess_observation_return=excess_observation_return,
            price_change_percentage=price_change_percentage,
            highest_close=highest_close,
            lowest_close=lowest_close,
            calculation_version=OBSERVATION_CALCULATION_VERSION,
            warnings=warnings,
        )

    # -- outcome ---------------------------------------------------------

    def _calculate_outcome_sync(
        self,
        scenario: HistoricalMarketScenario,
        focal_bars: list[MarketBar],
        benchmark_bars: list[MarketBar],
    ) -> ScenarioOutcome:
        decision_bars = [bar for bar in focal_bars if bar.timestamp <= scenario.decision_at]
        if not decision_bars:
            raise InsufficientScenarioDataError(
                f"No bar at or before decision_at is available for scenario '{scenario.scenario_id}'."
            )
        decision_bar = max(decision_bars, key=lambda bar: bar.timestamp)

        window_bars = [
            bar for bar in focal_bars if scenario.decision_at < bar.timestamp <= scenario.reveal_end_at
        ]
        frame, _warnings = _prepare_frame(window_bars)
        if len(frame) < scenario.minimum_reveal_bars:
            raise InsufficientScenarioDataError(
                f"Only {len(frame)} future reveal bars are available for scenario "
                f"'{scenario.scenario_id}'; {scenario.minimum_reveal_bars} are required."
            )

        adjusted_start = float(decision_bar.adjusted_close)
        adjusted = frame["adjusted_close"].astype(float)
        focal_end_close = float(frame["close"].iloc[-1])
        focal_return = float(adjusted.iloc[-1] / adjusted_start - 1.0)

        relative_series = adjusted.to_numpy() / adjusted_start - 1.0
        maximum_future_upside = float(max(0.0, relative_series.max()))
        maximum_future_drawdown = float(min(0.0, relative_series.min()))

        benchmark_decision_bars = [bar for bar in benchmark_bars if bar.timestamp <= scenario.decision_at]
        benchmark_window_bars = [
            bar
            for bar in benchmark_bars
            if scenario.decision_at < bar.timestamp <= scenario.reveal_end_at
        ]
        benchmark_frame, _benchmark_warnings = _prepare_frame(benchmark_window_bars)

        benchmark_return = None
        excess_return = None
        if benchmark_decision_bars and not benchmark_frame.empty:
            benchmark_decision_bar = max(benchmark_decision_bars, key=lambda bar: bar.timestamp)
            benchmark_adjusted_start = float(benchmark_decision_bar.adjusted_close)
            benchmark_adjusted_end = float(benchmark_frame["adjusted_close"].astype(float).iloc[-1])
            benchmark_return = benchmark_adjusted_end / benchmark_adjusted_start - 1.0
            excess_return = focal_return - benchmark_return

        outcome_direction = classify_outcome_direction(focal_return)

        return ScenarioOutcome(
            scenario_id=scenario.scenario_id,
            decision_at=scenario.decision_at,
            reveal_end_at=scenario.reveal_end_at,
            focal_start_close=float(decision_bar.close),
            focal_end_close=focal_end_close,
            focal_return=focal_return,
            maximum_future_upside=maximum_future_upside,
            maximum_future_drawdown=maximum_future_drawdown,
            benchmark_return=benchmark_return,
            excess_return=excess_return,
            outcome_direction=outcome_direction,
            outcome_summary=_build_outcome_summary(focal_return, outcome_direction),
            calculation_version=OUTCOME_CALCULATION_VERSION,
        )
