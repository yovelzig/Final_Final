"""Unit tests for `PandasScenarioCalculator`.

Deterministic, offline: synthetic `MarketBar` fixtures only, no
database, no network.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pandas as pd
import pytest

from stock_research_core.application.exceptions import InsufficientScenarioDataError
from stock_research_core.domain.market_scenarios.enums import (
    MarketScenarioType,
    ScenarioOutcomeDirection,
)
from stock_research_core.domain.market_scenarios.models import HistoricalMarketScenario
from stock_research_core.domain.market_scenarios.models import (
    ScenarioObservationMetrics,
    ScenarioOutcome,
)
from stock_research_core.domain.models import MarketBar
from stock_research_core.infrastructure.market_scenarios.pandas_scenario_calculator import (
    PandasScenarioCalculator,
)

NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)
_SECURITY_ID = uuid4()
_BENCHMARK_ID = uuid4()


def _bar(day_offset: int, close: float, *, volume: int = 1000, security_id=None) -> MarketBar:
    timestamp = NOW + timedelta(days=day_offset)
    return MarketBar(
        security_id=security_id or _SECURITY_ID,
        timestamp=timestamp,
        open=close,
        high=close + 0.5,
        low=close - 0.5,
        close=close,
        adjusted_close=close,
        volume=volume,
        interval="1d",
        source_name="test-source",
    )


def _scenario(
    *,
    observation_bars: int = 45,
    reveal_bars: int = 20,
    minimum_observation_bars: int = 40,
    minimum_reveal_bars: int = 20,
    benchmark_security_id=None,
) -> HistoricalMarketScenario:
    observation_start_at = NOW
    decision_at = NOW + timedelta(days=observation_bars - 1)
    reveal_end_at = decision_at + timedelta(days=reveal_bars)
    return HistoricalMarketScenario(
        exercise_id=uuid4(),
        code="TEST_SCENARIO",
        title="Test scenario",
        description="A synthetic scenario for calculator tests.",
        scenario_type=MarketScenarioType.MARKET_REPLAY,
        observation_start_at=observation_start_at,
        decision_at=decision_at,
        reveal_end_at=reveal_end_at,
        interval="1d",
        source_name="test-source",
        focal_security_id=_SECURITY_ID,
        benchmark_security_id=benchmark_security_id,
        primary_skill_ids=[uuid4()],
        prompt="What would you do?",
        learner_instructions="Decide.",
        learning_objectives=["Learn something."],
        minimum_observation_bars=minimum_observation_bars,
        minimum_reveal_bars=minimum_reveal_bars,
        scenario_version="scenario-v1",
    )


def _linear_bars(count: int, start_close: float = 100.0, step: float = 1.0, start_day: int = 0) -> list[MarketBar]:
    return [_bar(start_day + i, start_close + i * step, volume=1000 + i) for i in range(count)]


@pytest.fixture
def calculator() -> PandasScenarioCalculator:
    return PandasScenarioCalculator()


# ---------------------------------------------------------------------------
# calculate_observation
# ---------------------------------------------------------------------------


async def test_observation_return_and_price_change(calculator: PandasScenarioCalculator) -> None:
    scenario = _scenario(observation_bars=45, minimum_observation_bars=40)
    bars = _linear_bars(45)  # closes 100..144
    metrics = await calculator.calculate_observation(scenario=scenario, focal_bars=bars, benchmark_bars=[])

    assert isinstance(metrics, ScenarioObservationMetrics)
    assert metrics.observation_bar_count == 45
    assert metrics.start_close == pytest.approx(100.0)
    assert metrics.decision_close == pytest.approx(144.0)
    assert metrics.observation_return == pytest.approx(144.0 / 100.0 - 1.0)
    assert metrics.price_change_percentage == pytest.approx(44.0)
    assert metrics.highest_close == pytest.approx(144.0)
    assert metrics.lowest_close == pytest.approx(100.0)
    assert metrics.calculation_version == "scenario-observation-v1"


async def test_observation_average_volume(calculator: PandasScenarioCalculator) -> None:
    scenario = _scenario(observation_bars=45, minimum_observation_bars=40)
    bars = _linear_bars(45)
    metrics = await calculator.calculate_observation(scenario=scenario, focal_bars=bars, benchmark_bars=[])
    expected_average_volume = sum(1000 + i for i in range(45)) / 45
    assert metrics.average_daily_volume == pytest.approx(expected_average_volume)


async def test_observation_maximum_drawdown_is_zero_for_monotonic_rise(
    calculator: PandasScenarioCalculator,
) -> None:
    scenario = _scenario(observation_bars=45, minimum_observation_bars=40)
    bars = _linear_bars(45)
    metrics = await calculator.calculate_observation(scenario=scenario, focal_bars=bars, benchmark_bars=[])
    assert metrics.maximum_drawdown == pytest.approx(0.0)


async def test_observation_maximum_drawdown_matches_hand_computation(
    calculator: PandasScenarioCalculator,
) -> None:
    # 40 flat bars, then a sharp rise, then a sharp fall - a known drawdown.
    closes = [100.0] * 38 + [120.0, 90.0]
    scenario = _scenario(observation_bars=len(closes), minimum_observation_bars=len(closes))
    bars = [_bar(i, close) for i, close in enumerate(closes)]
    metrics = await calculator.calculate_observation(scenario=scenario, focal_bars=bars, benchmark_bars=[])
    expected_drawdown = 90.0 / 120.0 - 1.0
    assert metrics.maximum_drawdown == pytest.approx(expected_drawdown)


async def test_observation_annualized_volatility_near_zero_for_constant_growth(
    calculator: PandasScenarioCalculator,
) -> None:
    scenario = _scenario(observation_bars=45, minimum_observation_bars=40)
    bars = [_bar(i, 100.0 * (1.01**i)) for i in range(45)]  # constant daily log return
    metrics = await calculator.calculate_observation(scenario=scenario, focal_bars=bars, benchmark_bars=[])
    assert metrics.annualized_volatility is not None
    assert metrics.annualized_volatility == pytest.approx(0.0, abs=1e-6)


async def test_observation_benchmark_return_and_excess_return(calculator: PandasScenarioCalculator) -> None:
    scenario = _scenario(observation_bars=45, minimum_observation_bars=40, benchmark_security_id=_BENCHMARK_ID)
    focal_bars = _linear_bars(45)  # 100 -> 144, return 0.44
    benchmark_bars = [_bar(i, 200.0 + i, security_id=_BENCHMARK_ID) for i in range(45)]  # 200 -> 244
    metrics = await calculator.calculate_observation(
        scenario=scenario, focal_bars=focal_bars, benchmark_bars=benchmark_bars
    )
    expected_benchmark_return = 244.0 / 200.0 - 1.0
    assert metrics.benchmark_observation_return == pytest.approx(expected_benchmark_return)
    assert metrics.excess_observation_return == pytest.approx(metrics.observation_return - expected_benchmark_return)


async def test_observation_bars_are_sorted_deterministically(calculator: PandasScenarioCalculator) -> None:
    scenario = _scenario(observation_bars=45, minimum_observation_bars=40)
    ordered_bars = _linear_bars(45)
    shuffled_bars = list(ordered_bars)
    random.Random(42).shuffle(shuffled_bars)

    ordered_metrics = await calculator.calculate_observation(
        scenario=scenario, focal_bars=ordered_bars, benchmark_bars=[]
    )
    shuffled_metrics = await calculator.calculate_observation(
        scenario=scenario, focal_bars=shuffled_bars, benchmark_bars=[]
    )
    assert ordered_metrics == shuffled_metrics


async def test_observation_duplicate_timestamps_handled_deterministically(
    calculator: PandasScenarioCalculator,
) -> None:
    scenario = _scenario(observation_bars=40, minimum_observation_bars=40)
    bars = _linear_bars(40)
    # Duplicate the last bar's timestamp with a different close - "last wins".
    duplicate = _bar(39, 999.0)
    metrics = await calculator.calculate_observation(
        scenario=scenario, focal_bars=[*bars, duplicate], benchmark_bars=[]
    )
    assert metrics.observation_bar_count == 40
    assert metrics.decision_close == pytest.approx(999.0)
    assert metrics.warnings


async def test_observation_ignores_bars_after_decision_cutoff(calculator: PandasScenarioCalculator) -> None:
    scenario = _scenario(observation_bars=45, minimum_observation_bars=40)
    bars = _linear_bars(45)
    baseline = await calculator.calculate_observation(scenario=scenario, focal_bars=bars, benchmark_bars=[])

    future_bars = _linear_bars(20, start_close=999.0, start_day=45)
    with_future = await calculator.calculate_observation(
        scenario=scenario, focal_bars=[*bars, *future_bars], benchmark_bars=[]
    )
    assert with_future == baseline


async def test_observation_insufficient_bars_raises(calculator: PandasScenarioCalculator) -> None:
    scenario = _scenario(observation_bars=45, minimum_observation_bars=40)
    bars = _linear_bars(10)
    with pytest.raises(InsufficientScenarioDataError):
        await calculator.calculate_observation(scenario=scenario, focal_bars=bars, benchmark_bars=[])


async def test_observation_calculation_is_deterministic(calculator: PandasScenarioCalculator) -> None:
    scenario = _scenario(observation_bars=45, minimum_observation_bars=40)
    bars = _linear_bars(45)
    first = await calculator.calculate_observation(scenario=scenario, focal_bars=bars, benchmark_bars=[])
    second = await calculator.calculate_observation(scenario=scenario, focal_bars=bars, benchmark_bars=[])
    assert first == second


def test_observation_never_returns_a_dataframe(calculator: PandasScenarioCalculator) -> None:
    import asyncio

    scenario = _scenario(observation_bars=45, minimum_observation_bars=40)
    bars = _linear_bars(45)
    result = asyncio.run(
        calculator.calculate_observation(scenario=scenario, focal_bars=bars, benchmark_bars=[])
    )
    assert not isinstance(result, pd.DataFrame)
    assert isinstance(result, ScenarioObservationMetrics)


# ---------------------------------------------------------------------------
# calculate_outcome
# ---------------------------------------------------------------------------


async def test_outcome_focal_return_upside_and_drawdown(calculator: PandasScenarioCalculator) -> None:
    scenario = _scenario(observation_bars=40, reveal_bars=20, minimum_observation_bars=40, minimum_reveal_bars=20)
    observation_bars = _linear_bars(40)  # decision close = 100 + 39 = 139
    # Reveal window: rises to 160 then falls to 130.
    reveal_closes = [140.0, 150.0, 160.0] + [155.0] * 10 + [130.0] * 7
    reveal_bars = [_bar(40 + i, close) for i, close in enumerate(reveal_closes)]

    outcome = await calculator.calculate_outcome(
        scenario=scenario, focal_bars=[*observation_bars, *reveal_bars], benchmark_bars=[]
    )
    assert isinstance(outcome, ScenarioOutcome)
    decision_close = 139.0
    assert outcome.focal_start_close == pytest.approx(decision_close)
    assert outcome.focal_end_close == pytest.approx(130.0)
    expected_return = 130.0 / decision_close - 1.0
    assert outcome.focal_return == pytest.approx(expected_return)
    assert outcome.maximum_future_upside == pytest.approx(160.0 / decision_close - 1.0)
    assert outcome.maximum_future_drawdown == pytest.approx(130.0 / decision_close - 1.0)
    assert outcome.calculation_version == "scenario-outcome-v1"


async def test_outcome_benchmark_return_and_excess_return(calculator: PandasScenarioCalculator) -> None:
    scenario = _scenario(
        observation_bars=40,
        reveal_bars=20,
        minimum_observation_bars=40,
        minimum_reveal_bars=20,
        benchmark_security_id=_BENCHMARK_ID,
    )
    focal_bars = _linear_bars(60)
    benchmark_bars = [_bar(i, 200.0 + i, security_id=_BENCHMARK_ID) for i in range(60)]

    outcome = await calculator.calculate_outcome(
        scenario=scenario, focal_bars=focal_bars, benchmark_bars=benchmark_bars
    )
    benchmark_decision_close = 200.0 + 39
    benchmark_end_close = 200.0 + 59
    expected_benchmark_return = benchmark_end_close / benchmark_decision_close - 1.0
    assert outcome.benchmark_return == pytest.approx(expected_benchmark_return)
    assert outcome.excess_return == pytest.approx(outcome.focal_return - expected_benchmark_return)


@pytest.mark.parametrize(
    ("focal_return_target", "expected_direction"),
    [
        (0.02, ScenarioOutcomeDirection.POSITIVE),
        (-0.02, ScenarioOutcomeDirection.NEGATIVE),
        (0.005, ScenarioOutcomeDirection.FLAT),
        (-0.005, ScenarioOutcomeDirection.FLAT),
    ],
)
async def test_outcome_direction_thresholds(
    calculator: PandasScenarioCalculator, focal_return_target: float, expected_direction: ScenarioOutcomeDirection
) -> None:
    scenario = _scenario(observation_bars=40, reveal_bars=20, minimum_observation_bars=40, minimum_reveal_bars=20)
    observation_bars = _linear_bars(40, start_close=100.0, step=0.0)  # flat at 100
    decision_close = 100.0
    end_close = decision_close * (1 + focal_return_target)
    reveal_bars = [_bar(40 + i, end_close) for i in range(20)]

    outcome = await calculator.calculate_outcome(
        scenario=scenario, focal_bars=[*observation_bars, *reveal_bars], benchmark_bars=[]
    )
    assert outcome.outcome_direction == expected_direction


async def test_outcome_ignores_bars_at_or_before_decision(calculator: PandasScenarioCalculator) -> None:
    scenario = _scenario(observation_bars=40, reveal_bars=20, minimum_observation_bars=40, minimum_reveal_bars=20)
    observation_bars = _linear_bars(40)
    reveal_bars = _linear_bars(20, start_close=500.0, start_day=40)

    baseline = await calculator.calculate_outcome(
        scenario=scenario, focal_bars=[*observation_bars, *reveal_bars], benchmark_bars=[]
    )
    # Mutate an observation-window bar's close far away from its real value;
    # since the outcome calculation must ignore it, the result is unchanged.
    tampered_observation_bars = list(observation_bars)
    tampered_observation_bars[0] = _bar(0, 999999.0)
    tampered = await calculator.calculate_outcome(
        scenario=scenario, focal_bars=[*tampered_observation_bars, *reveal_bars], benchmark_bars=[]
    )
    assert tampered.model_dump(exclude={"outcome_id", "calculated_at"}) == baseline.model_dump(
        exclude={"outcome_id", "calculated_at"}
    )


async def test_outcome_insufficient_reveal_bars_raises(calculator: PandasScenarioCalculator) -> None:
    scenario = _scenario(observation_bars=40, reveal_bars=20, minimum_observation_bars=40, minimum_reveal_bars=20)
    observation_bars = _linear_bars(40)
    too_few_reveal_bars = _linear_bars(5, start_close=140.0, start_day=40)
    with pytest.raises(InsufficientScenarioDataError):
        await calculator.calculate_outcome(
            scenario=scenario, focal_bars=[*observation_bars, *too_few_reveal_bars], benchmark_bars=[]
        )


async def test_outcome_calculation_is_deterministic(calculator: PandasScenarioCalculator) -> None:
    scenario = _scenario(observation_bars=40, reveal_bars=20, minimum_observation_bars=40, minimum_reveal_bars=20)
    bars = _linear_bars(60)
    first = await calculator.calculate_outcome(scenario=scenario, focal_bars=bars, benchmark_bars=[])
    second = await calculator.calculate_outcome(scenario=scenario, focal_bars=bars, benchmark_bars=[])
    assert first.model_dump(exclude={"outcome_id", "calculated_at"}) == second.model_dump(
        exclude={"outcome_id", "calculated_at"}
    )
