"""The scenario-calculation Protocol, its version constants, and the
deterministic outcome-direction classifier.

Implementations may use pandas/NumPy - but only in infrastructure
(`stock_research_core.infrastructure.market_scenarios`). This module
stays pure so both the application layer and its tests can import it
without pulling in a heavyweight numerical dependency.
"""

from __future__ import annotations

from typing import Protocol

from stock_research_core.domain.market_scenarios.enums import ScenarioOutcomeDirection
from stock_research_core.domain.market_scenarios.models import (
    HistoricalMarketScenario,
    ScenarioObservationMetrics,
    ScenarioOutcome,
)
from stock_research_core.domain.models import MarketBar

#: Calculator versions. Every `ScenarioObservationMetrics`/`ScenarioOutcome`
#: this codebase produces must carry one of these, so the same stored
#: bars + version always reproduce the same numbers.
OBSERVATION_CALCULATION_VERSION = "scenario-observation-v1"
OUTCOME_CALCULATION_VERSION = "scenario-outcome-v1"

#: A realized focal return beyond this band (in either direction) is
#: classified POSITIVE/NEGATIVE; anything within the band is FLAT.
#: Documented threshold per spec: "POSITIVE when focal return > +1%,
#: NEGATIVE when focal return < -1%, FLAT otherwise".
OUTCOME_POSITIVE_THRESHOLD = 0.01
OUTCOME_NEGATIVE_THRESHOLD = -0.01


def classify_outcome_direction(focal_return: float) -> ScenarioOutcomeDirection:
    """scenario-outcome-v1's deterministic direction classifier (see the
    threshold constants above). Shared by `PandasScenarioCalculator` and
    its tests so the threshold is defined exactly once.
    """
    if focal_return > OUTCOME_POSITIVE_THRESHOLD:
        return ScenarioOutcomeDirection.POSITIVE
    if focal_return < OUTCOME_NEGATIVE_THRESHOLD:
        return ScenarioOutcomeDirection.NEGATIVE
    return ScenarioOutcomeDirection.FLAT


class ScenarioCalculatorPort(Protocol):
    """Computes deterministic, point-in-time-safe scenario metrics from
    already-stored `MarketBar` objects. Never queries a database, never
    calls yfinance, and never reads bars outside the window it was
    asked to compute over.
    """

    async def calculate_observation(
        self,
        *,
        scenario: HistoricalMarketScenario,
        focal_bars: list[MarketBar],
        benchmark_bars: list[MarketBar],
    ) -> ScenarioObservationMetrics:
        """Uses only bars with `observation_start_at <= timestamp <=
        decision_at`."""
        ...

    async def calculate_outcome(
        self,
        *,
        scenario: HistoricalMarketScenario,
        focal_bars: list[MarketBar],
        benchmark_bars: list[MarketBar],
    ) -> ScenarioOutcome:
        """Uses only bars with `decision_at < timestamp <= reveal_end_at`."""
        ...
