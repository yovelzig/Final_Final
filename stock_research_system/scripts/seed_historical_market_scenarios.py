"""Seed historical market decision scenarios from already-stored bars.

Deterministic and idempotent: every scenario/exercise/option/rubric ID
is derived via `uuid.uuid5` from a stable key (the scenario code, which
itself is derived from the ticker and decision date), so re-running
this script updates the same rows in place instead of creating
duplicates. Requires prior market-data ingestion (e.g.
`stock_research_core.cli.market_data` or
`stock_research_core.cli.ingest_and_store`) - this script never calls
yfinance, it only reads bars already stored in `market_bars`.

Window selection is fully deterministic: given N stored daily bars, up
to `--scenario-count` decision points are chosen at evenly spaced
positions across the valid range (a position needs >= 40 bars before
it for observation and >= 20 bars after it for reveal). No randomness
is used anywhere in this script.

Usage (PowerShell):

    python scripts/seed_historical_market_scenarios.py `
      --ticker NVDA `
      --benchmark SPY `
      --scenario-count 4

No investment recommendations and no future-outcome language appear in
any seeded prompt, instruction, or rubric - rubric component scores
reflect the quality of reasoning represented by each option, never the
security's actual later return.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from stock_research_core.application.exceptions import StockResearchError
from stock_research_core.application.learning.service import LearningService
from stock_research_core.application.market_scenarios.grading import RuleBasedScenarioGradingPolicy
from stock_research_core.application.market_scenarios.service import HistoricalMarketScenarioService
from stock_research_core.domain.adaptive_learning.models import ExerciseAdaptiveProfile
from stock_research_core.domain.learning.enums import (
    DifficultyLevel,
    ExerciseType,
    FinancialSkillCategory,
    LessonStatus,
)
from stock_research_core.domain.learning.models import (
    Exercise,
    ExerciseOption,
    LearningModule,
    LearningPath,
    Lesson,
    Skill,
)
from stock_research_core.domain.market_scenarios.enums import (
    MarketScenarioStatus,
    MarketScenarioType,
    ScenarioExpectedDirection,
    ScenarioFeedbackCode,
    ScenarioGenerationRunStatus,
)
from stock_research_core.domain.market_scenarios.models import (
    RUBRIC_COMPONENT_WEIGHTS,
    HistoricalMarketScenario,
    ScenarioGenerationRun,
    ScenarioOptionRubric,
)
from stock_research_core.domain.models import MarketBar
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from stock_research_core.infrastructure.market_scenarios.pandas_scenario_calculator import (
    PandasScenarioCalculator,
)

_NAMESPACE = uuid.UUID("f1a4a1e0-3333-4000-8000-000000000000")

_MINIMUM_OBSERVATION_BARS = 40
_MINIMUM_REVEAL_BARS = 20
_SCENARIO_VERSION = "scenario-v1"
_INTERVAL = "1d"

_PATH_ID = uuid.uuid5(_NAMESPACE, "path:historical-market-scenarios")
_MODULE_ID = uuid.uuid5(_NAMESPACE, "module:historical-market-scenarios")
_LESSON_ID = uuid.uuid5(_NAMESPACE, "lesson:historical-market-scenarios")

_TARGET_SKILLS: dict[str, dict] = {
    "RISK_AND_RETURN": dict(
        name="Risk and Return",
        description=(
            "Understand the basic relationship between the risk an investment carries and its "
            "potential return."
        ),
        category=FinancialSkillCategory.RISK_AND_RETURN,
    ),
    "MARKET_INDEXES": dict(
        name="Market Indexes",
        description="Understand what a market index is and why it is used as a benchmark.",
        category=FinancialSkillCategory.MARKET_INDEXES,
    ),
    "CHART_READING": dict(
        name="Chart Reading",
        description="Read a price chart and describe what it shows without predicting the future.",
        category=FinancialSkillCategory.CHART_READING,
    ),
    "LONG_TERM_INVESTING": dict(
        name="Long-Term Investing",
        description="Understand why matching a decision to a time horizon matters for investing.",
        category=FinancialSkillCategory.LONG_TERM_INVESTING,
    ),
}


def _id(key: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, key)


@dataclass(frozen=True)
class OptionSpec:
    key: str
    content: str
    risk_awareness_score: float
    benchmark_awareness_score: float
    horizon_alignment_score: float
    information_sufficiency_score: float
    uncertainty_awareness_score: float
    expected_direction: ScenarioExpectedDirection
    feedback_codes: list[ScenarioFeedbackCode]
    positive_feedback: str
    improvement_feedback: str

    def decision_quality_score(self) -> float:
        scores = {
            "risk_awareness_score": self.risk_awareness_score,
            "benchmark_awareness_score": self.benchmark_awareness_score,
            "horizon_alignment_score": self.horizon_alignment_score,
            "information_sufficiency_score": self.information_sufficiency_score,
            "uncertainty_awareness_score": self.uncertainty_awareness_score,
        }
        return sum(scores[name] * weight for name, weight in RUBRIC_COMPONENT_WEIGHTS.items())


#: Five deterministic, ticker-agnostic decision options reused for
#: every generated scenario. Component scores reflect the quality of
#: the reasoning each option represents - never a realized return.
_OPTION_SPECS: list[OptionSpec] = [
    OptionSpec(
        key="invest_now",
        content="Invest immediately because the recent rise will probably continue.",
        risk_awareness_score=0.15,
        benchmark_awareness_score=0.20,
        horizon_alignment_score=0.30,
        information_sufficiency_score=0.20,
        uncertainty_awareness_score=0.15,
        expected_direction=ScenarioExpectedDirection.POSITIVE,
        feedback_codes=[ScenarioFeedbackCode.IGNORED_RISK, ScenarioFeedbackCode.IGNORED_BENCHMARK],
        positive_feedback="You noticed the recent upward movement in the chart.",
        improvement_feedback=(
            "Chasing a recent trend without weighing risk or comparing to a benchmark is a "
            "common bias - consider risk-adjusted, diversified alternatives instead."
        ),
    ),
    OptionSpec(
        key="wait_for_information",
        content="Wait for more information before making a decision.",
        risk_awareness_score=0.65,
        benchmark_awareness_score=0.60,
        horizon_alignment_score=0.55,
        information_sufficiency_score=0.90,
        uncertainty_awareness_score=0.80,
        expected_direction=ScenarioExpectedDirection.INFORMATION_REQUIRED,
        feedback_codes=[
            ScenarioFeedbackCode.REQUESTED_MORE_INFORMATION,
            ScenarioFeedbackCode.RECOGNIZED_UNCERTAINTY,
        ],
        positive_feedback=(
            "You recognized that the information available up to the decision point may not be "
            "sufficient to act on confidently."
        ),
        improvement_feedback=(
            "Waiting is reasonable, but try to name the specific additional information that "
            "would actually change your decision."
        ),
    ),
    OptionSpec(
        key="diversified_fund",
        content="Prefer a diversified market fund because the single-stock risk is high.",
        risk_awareness_score=0.90,
        benchmark_awareness_score=0.85,
        horizon_alignment_score=0.75,
        information_sufficiency_score=0.70,
        uncertainty_awareness_score=0.70,
        expected_direction=ScenarioExpectedDirection.NEUTRAL,
        feedback_codes=[ScenarioFeedbackCode.IDENTIFIED_RISK, ScenarioFeedbackCode.CONSIDERED_BENCHMARK],
        positive_feedback=(
            "You identified the concentration risk in a single stock and considered a "
            "diversified, benchmark-aware alternative."
        ),
        improvement_feedback="Keep connecting single-stock decisions back to your overall diversified plan.",
    ),
    OptionSpec(
        key="small_long_term_position",
        content="Consider a small position only if it fits a long-term diversified plan.",
        risk_awareness_score=0.85,
        benchmark_awareness_score=0.75,
        horizon_alignment_score=0.90,
        information_sufficiency_score=0.70,
        uncertainty_awareness_score=0.65,
        expected_direction=ScenarioExpectedDirection.NEUTRAL,
        feedback_codes=[ScenarioFeedbackCode.IDENTIFIED_RISK, ScenarioFeedbackCode.MATCHED_TIME_HORIZON],
        positive_feedback=(
            "You sized the position conservatively and matched it to a long-term time horizon."
        ),
        improvement_feedback="Continue to be explicit about how any single position fits your broader plan.",
    ),
    OptionSpec(
        key="avoid_recent_decline",
        content="Avoid the investment solely because the price recently declined.",
        risk_awareness_score=0.25,
        benchmark_awareness_score=0.20,
        horizon_alignment_score=0.15,
        information_sufficiency_score=0.20,
        uncertainty_awareness_score=0.20,
        expected_direction=ScenarioExpectedDirection.NEGATIVE,
        feedback_codes=[
            ScenarioFeedbackCode.IGNORED_RISK,
            ScenarioFeedbackCode.MISMATCHED_TIME_HORIZON,
        ],
        positive_feedback="You noticed the recent price decline.",
        improvement_feedback=(
            "Avoiding an investment solely because of a recent price drop, without further "
            "analysis, is a reactive decision rather than a risk-aware one."
        ),
    ),
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed historical market decision scenarios.")
    parser.add_argument("--ticker", required=True, help="Focal security ticker (must already be stored)")
    parser.add_argument("--benchmark", default=None, help="Optional benchmark ticker (must already be stored)")
    parser.add_argument(
        "--scenario-count", type=int, default=4, help="Maximum number of scenarios to generate"
    )
    return parser.parse_args()


def _select_decision_positions(bar_count: int, scenario_count: int) -> list[int]:
    """Deterministic, evenly spaced decision-bar indices (0-indexed into
    the ascending bar list). A valid position needs
    `_MINIMUM_OBSERVATION_BARS` bars at or before it and
    `_MINIMUM_REVEAL_BARS` bars strictly after it.
    """
    valid_start = _MINIMUM_OBSERVATION_BARS - 1
    valid_end = bar_count - 1 - _MINIMUM_REVEAL_BARS
    if valid_end < valid_start:
        return []
    if scenario_count <= 1 or valid_end == valid_start:
        return [valid_start + (valid_end - valid_start) // 2]

    span = valid_end - valid_start
    positions = sorted(
        {
            valid_start + round(i * span / (scenario_count - 1))
            for i in range(scenario_count)
        }
    )
    return positions


async def _ensure_curriculum_scaffold(uow: SqlAlchemyUnitOfWork) -> dict[str, uuid.UUID]:
    """Idempotently ensures the shared path/module/lesson and the four
    target skills exist, reusing any skill already seeded elsewhere
    (matched by `code`) instead of creating a duplicate.
    """
    existing_skills = {skill.code: skill for skill in await uow.curriculum.list_skills(active_only=False)}
    skill_ids: dict[str, uuid.UUID] = {}
    for code, spec in _TARGET_SKILLS.items():
        if code in existing_skills:
            skill_ids[code] = existing_skills[code].skill_id
            continue
        skill = Skill(
            skill_id=_id(f"skill:{code}"),
            code=code,
            name=spec["name"],
            description=spec["description"],
            category=spec["category"],
            difficulty=DifficultyLevel.MEDIUM,
        )
        created = await uow.curriculum.upsert_skill(skill)
        skill_ids[code] = created.skill_id

    await uow.curriculum.upsert_path(
        LearningPath(
            path_id=_PATH_ID,
            code="historical-market-scenarios",
            title="Historical Market Scenarios",
            description=(
                "Practice investment decisions using real historical market data, with future "
                "prices hidden until after you decide."
            ),
            difficulty=DifficultyLevel.MEDIUM,
            position=100,
            estimated_minutes=10,
            published=True,
        )
    )
    await uow.curriculum.upsert_module(
        LearningModule(
            module_id=_MODULE_ID,
            path_id=_PATH_ID,
            code="historical-market-scenarios-module",
            title="Historical Market Scenarios",
            description="Point-in-time investment decision exercises built from real market history.",
            position=0,
            estimated_minutes=10,
            published=True,
        )
    )
    await uow.curriculum.upsert_lesson(
        Lesson(
            lesson_id=_LESSON_ID,
            module_id=_MODULE_ID,
            code="historical-market-scenarios-lesson",
            title="Historical Market Scenarios",
            summary="Make a point-in-time investment decision, then see how the market actually moved.",
            content_markdown=(
                "# Historical Market Scenarios\n\n"
                "Each scenario below shows real historical market data up to a specific decision "
                "point. Future prices are hidden until after you submit your decision. Your score "
                "is based on the quality of your reasoning, not on whether the market later moved "
                "in your favor."
            ),
            difficulty=DifficultyLevel.MEDIUM,
            status=LessonStatus.PUBLISHED,
            position=0,
            estimated_minutes=10,
            primary_skill_id=skill_ids["RISK_AND_RETURN"],
            secondary_skill_ids=[
                skill_ids["MARKET_INDEXES"],
                skill_ids["CHART_READING"],
                skill_ids["LONG_TERM_INVESTING"],
            ],
        )
    )
    return skill_ids


async def _load_all_daily_bars(uow: SqlAlchemyUnitOfWork, security_id: uuid.UUID) -> list[MarketBar]:
    return await uow.market_bars.list_range(
        security_id,
        datetime(1970, 1, 1, tzinfo=timezone.utc),
        datetime.now(timezone.utc),
        interval=_INTERVAL,
    )


async def seed() -> None:
    args = _parse_args()
    ticker = args.ticker.upper()
    benchmark_ticker = args.benchmark.upper() if args.benchmark else None

    settings = DatabaseSettings()
    engine = create_database_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        unit_of_work_factory = lambda: SqlAlchemyUnitOfWork(session_factory)  # noqa: E731

        async with unit_of_work_factory() as uow:
            focal_security = await uow.securities.get_by_ticker(ticker)
            if focal_security is None:
                print(
                    f"error: no stored security found for ticker '{ticker}'. Run market-data "
                    "ingestion for this ticker before seeding scenarios.",
                    file=sys.stderr,
                )
                return

            benchmark_security = None
            if benchmark_ticker is not None:
                benchmark_security = await uow.securities.get_by_ticker(benchmark_ticker)
                if benchmark_security is None:
                    print(
                        f"error: no stored security found for benchmark ticker '{benchmark_ticker}'. "
                        "Run market-data ingestion for this ticker before seeding scenarios.",
                        file=sys.stderr,
                    )
                    return

            skill_ids = await _ensure_curriculum_scaffold(uow)
            focal_bars = await _load_all_daily_bars(uow, focal_security.security_id)
            benchmark_bars = (
                await _load_all_daily_bars(uow, benchmark_security.security_id)
                if benchmark_security is not None
                else []
            )
            await uow.commit()

        positions = _select_decision_positions(len(focal_bars), args.scenario_count)
        if not positions:
            print(
                f"Only {len(focal_bars)} stored daily bars are available for '{ticker}'; at least "
                f"{_MINIMUM_OBSERVATION_BARS + _MINIMUM_REVEAL_BARS} are required to seed even one "
                "scenario. Ingest more history first."
            )
            return

        target_skill_ids = [
            skill_ids["RISK_AND_RETURN"],
            skill_ids["CHART_READING"],
            skill_ids["MARKET_INDEXES"],
            skill_ids["LONG_TERM_INVESTING"],
        ]

        market_scenario_service = HistoricalMarketScenarioService(
            unit_of_work_factory=unit_of_work_factory,
            scenario_calculator=PandasScenarioCalculator(),
            scenario_grading_policy=RuleBasedScenarioGradingPolicy(),
            graded_answer_submitter=LearningService(unit_of_work_factory),
        )

        published_count = 0
        for position, index in zip(positions, range(len(positions))):
            published = await _seed_one_scenario(
                unit_of_work_factory=unit_of_work_factory,
                market_scenario_service=market_scenario_service,
                ticker=ticker,
                focal_security_id=focal_security.security_id,
                benchmark_security_id=(
                    benchmark_security.security_id if benchmark_security is not None else None
                ),
                focal_bars=focal_bars,
                position=position,
                exercise_position=index,
                target_skill_ids=target_skill_ids,
            )
            if published:
                published_count += 1

        print(
            f"Seeded {len(positions)} scenario window(s) for '{ticker}' "
            f"({published_count} published)."
        )
    finally:
        await engine.dispose()


async def _seed_one_scenario(
    *,
    unit_of_work_factory,  # noqa: ANN001
    market_scenario_service: HistoricalMarketScenarioService,
    ticker: str,
    focal_security_id: uuid.UUID,
    benchmark_security_id: uuid.UUID | None,
    focal_bars: list[MarketBar],
    position: int,
    exercise_position: int,
    target_skill_ids: list[uuid.UUID],
) -> bool:
    observation_start = focal_bars[position - _MINIMUM_OBSERVATION_BARS + 1].timestamp
    decision_at = focal_bars[position].timestamp
    reveal_end_at = focal_bars[position + _MINIMUM_REVEAL_BARS].timestamp

    decision_date_key = decision_at.strftime("%Y%m%d")
    scenario_code = f"{ticker}_{decision_date_key}"
    scenario_id = _id(f"scenario:{scenario_code}")
    exercise_id = _id(f"exercise:{scenario_code}")

    run = ScenarioGenerationRun(
        run_id=uuid.uuid4(),
        status=ScenarioGenerationRunStatus.STARTED,
        focal_security_id=focal_security_id,
        benchmark_security_id=benchmark_security_id,
        requested_observation_start_at=observation_start,
        requested_decision_at=decision_at,
        requested_reveal_end_at=reveal_end_at,
        scenario_code=scenario_code,
        scenario_version=_SCENARIO_VERSION,
    )

    async with unit_of_work_factory() as uow:
        stored_run = await uow.scenario_generation_runs.create(run)
        await uow.commit()

    options = [
        ExerciseOption(
            option_id=_id(f"scenario_option:{scenario_code}:{spec.key}"),
            exercise_id=exercise_id,
            option_key=spec.key,
            content=spec.content,
            position=position_index,
            is_correct=False,
        )
        for position_index, spec in enumerate(_OPTION_SPECS)
    ]

    exercise = Exercise(
        exercise_id=exercise_id,
        lesson_id=_LESSON_ID,
        exercise_type=ExerciseType.SCENARIO_DECISION,
        prompt=(
            "Based only on the information available up to the decision date shown above, which "
            "of the following actions best reflects a sound, risk-aware investment decision?"
        ),
        explanation=(
            "This is a historical market scenario. Feedback on your decision quality is provided "
            "after you submit; the realized market outcome is revealed separately afterward."
        ),
        difficulty=DifficultyLevel.MEDIUM,
        position=exercise_position,
        skill_ids=target_skill_ids,
        maximum_score=1.0,
        passing_score=0.6,
    )

    scenario = HistoricalMarketScenario(
        scenario_id=scenario_id,
        exercise_id=exercise_id,
        code=scenario_code,
        title=f"{ticker} decision scenario - {decision_at.date().isoformat()}",
        description=(
            f"A point-in-time investment decision for {ticker}, using real historical market data "
            f"up to {decision_at.date().isoformat()}. Future prices are hidden until after you decide."
        ),
        scenario_type=(
            MarketScenarioType.BENCHMARK_COMPARISON
            if benchmark_security_id is not None
            else MarketScenarioType.MARKET_REPLAY
        ),
        status=MarketScenarioStatus.DRAFT,
        observation_start_at=observation_start,
        decision_at=decision_at,
        reveal_end_at=reveal_end_at,
        interval=_INTERVAL,
        source_name=focal_bars[0].source_name,
        focal_security_id=focal_security_id,
        benchmark_security_id=benchmark_security_id,
        primary_skill_ids=target_skill_ids[:2],
        secondary_skill_ids=target_skill_ids[2:],
        prompt=exercise.prompt,
        learner_instructions=(
            "Review the chart and observation metrics above. Consider risk, diversification, and "
            "your time horizon before choosing an option. You will not be able to see what happened "
            "after the decision date until after you submit your choice."
        ),
        learning_objectives=[
            "Distinguish between decision quality and realized market outcome.",
            "Practice incorporating risk and benchmark comparison into an investment decision.",
            "Recognize when more information should be requested before deciding.",
        ],
        minimum_observation_bars=_MINIMUM_OBSERVATION_BARS,
        minimum_reveal_bars=_MINIMUM_REVEAL_BARS,
        scenario_version=_SCENARIO_VERSION,
    )

    rubrics = [
        ScenarioOptionRubric(
            rubric_id=_id(f"scenario_rubric:{scenario_code}:{spec.key}"),
            scenario_id=scenario_id,
            exercise_option_id=option.option_id,
            decision_quality_score=spec.decision_quality_score(),
            risk_awareness_score=spec.risk_awareness_score,
            benchmark_awareness_score=spec.benchmark_awareness_score,
            horizon_alignment_score=spec.horizon_alignment_score,
            information_sufficiency_score=spec.information_sufficiency_score,
            uncertainty_awareness_score=spec.uncertainty_awareness_score,
            expected_direction=spec.expected_direction,
            feedback_codes=spec.feedback_codes,
            positive_feedback=spec.positive_feedback,
            improvement_feedback=spec.improvement_feedback,
            rubric_version="scenario-rubric-v1",
        )
        for option, spec in zip(options, _OPTION_SPECS)
    ]

    try:
        async with unit_of_work_factory() as uow:
            await uow.curriculum.upsert_exercise(exercise)
            await uow.curriculum.upsert_options(options)
            await uow.commit()

        stored_scenario = await market_scenario_service.create_or_update_scenario(
            scenario=scenario.model_copy(update={"status": MarketScenarioStatus.PUBLISHED}),
            rubrics=rubrics,
        )

        async with unit_of_work_factory() as uow:
            await uow.adaptive_profiles.upsert(
                ExerciseAdaptiveProfile(
                    profile_id=_id(f"scenario_adaptive_profile:{exercise_id}"),
                    exercise_id=exercise_id,
                    base_difficulty_score=0.5,
                    estimated_seconds=180,
                    diagnostic_eligible=False,
                    review_eligible=True,
                    remediation_eligible=False,
                    policy_tags=[
                        "historical-scenario",
                        "risk-awareness",
                        "benchmark-comparison",
                        "time-horizon",
                    ],
                    active=True,
                )
            )
            await uow.scenario_generation_runs.mark_completed(
                stored_run.run_id,
                observation_bars_found=_MINIMUM_OBSERVATION_BARS,
                reveal_bars_found=_MINIMUM_REVEAL_BARS,
                benchmark_bars_found=0,
            )
            await uow.commit()

        print(f"  Seeded scenario '{scenario_code}' (status={stored_scenario.status.value}).")
        return stored_scenario.status == MarketScenarioStatus.PUBLISHED
    except StockResearchError as exc:
        async with unit_of_work_factory() as uow:
            await uow.scenario_generation_runs.mark_failed(
                stored_run.run_id, error_type=type(exc).__name__, error_message=str(exc)[:2000]
            )
            await uow.commit()
        print(f"  Skipped scenario '{scenario_code}': {exc}", file=sys.stderr)
        return False


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
