"""CLI for the FinQuest historical market scenario engine.

List published scenarios (PowerShell):

    python -m stock_research_core.cli.market_scenarios --list

View a learner-safe scenario (no future data, no rubric scores):

    python -m stock_research_core.cli.market_scenarios `
      --learner-id <UUID> --scenario-id <UUID> --view

Start a scenario against an already-started exercise attempt:

    python -m stock_research_core.cli.market_scenarios `
      --learner-id <UUID> --scenario-id <UUID> --attempt-id <UUID> --start

Submit a decision:

    python -m stock_research_core.cli.market_scenarios `
      --submission-id <UUID> --option-id <UUID> --confidence HIGH `
      --rationale "I would limit the position because the risk is concentrated." --submit

Reveal the realized outcome after grading:

    python -m stock_research_core.cli.market_scenarios --submission-id <UUID> --reveal

Validate an already-stored scenario:

    python -m stock_research_core.cli.market_scenarios --scenario-id <UUID> --validate

This module is a composition root: it is the one place outside the
infrastructure layer allowed to import concrete adapters directly.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from stock_research_core.application.exceptions import StockResearchError
from stock_research_core.application.learning.service import LearningService
from stock_research_core.application.market_scenarios.grading import RuleBasedScenarioGradingPolicy
from stock_research_core.application.market_scenarios.service import HistoricalMarketScenarioService
from stock_research_core.domain.learning.enums import ConfidenceLevel
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import (
    create_database_engine,
    create_session_factory,
)
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from stock_research_core.infrastructure.market_scenarios.pandas_scenario_calculator import (
    PandasScenarioCalculator,
)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stock_research_core.cli.market_scenarios",
        description="Drive the FinQuest historical market scenario engine.",
    )
    parser.add_argument("--learner-id", metavar="UUID", default=None, help="Target learner ID")
    parser.add_argument("--scenario-id", metavar="UUID", default=None, help="Target scenario ID")
    parser.add_argument("--attempt-id", metavar="UUID", default=None, help="Target exercise attempt ID")
    parser.add_argument("--submission-id", metavar="UUID", default=None, help="Target submission ID")
    parser.add_argument("--option-id", metavar="UUID", default=None, help="Selected exercise option ID")
    parser.add_argument(
        "--confidence",
        default=None,
        choices=[member.value for member in ConfidenceLevel],
        help="Confidence level for --submit",
    )
    parser.add_argument("--rationale", default=None, help="Learner rationale text for --submit")

    parser.add_argument("--list", dest="list_scenarios", action="store_true", help="List published scenarios")
    parser.add_argument("--view", action="store_true", help="View a learner-safe scenario")
    parser.add_argument("--start", action="store_true", help="Start a scenario")
    parser.add_argument("--submit", action="store_true", help="Submit a decision")
    parser.add_argument("--reveal", action="store_true", help="Reveal the realized outcome")
    parser.add_argument("--validate", action="store_true", help="Validate an already-stored scenario")
    return parser


def _build_service(unit_of_work_factory) -> HistoricalMarketScenarioService:  # noqa: ANN001
    return HistoricalMarketScenarioService(
        unit_of_work_factory=unit_of_work_factory,
        scenario_calculator=PandasScenarioCalculator(),
        scenario_grading_policy=RuleBasedScenarioGradingPolicy(),
        graded_answer_submitter=LearningService(unit_of_work_factory),
    )


async def _list_scenarios(unit_of_work_factory) -> None:  # noqa: ANN001
    async with unit_of_work_factory() as uow:
        scenarios = await uow.market_scenarios.list_published()
        print(f"Published scenarios ({len(scenarios)}):")
        for scenario in scenarios:
            focal = await uow.securities.get_by_id(scenario.focal_security_id)
            benchmark = (
                await uow.securities.get_by_id(scenario.benchmark_security_id)
                if scenario.benchmark_security_id is not None
                else None
            )
            print(f"  - {scenario.scenario_id}")
            print(f"    Code:            {scenario.code}")
            print(f"    Title:           {scenario.title}")
            print(f"    Type:            {scenario.scenario_type.value}")
            print(f"    Focal ticker:    {focal.ticker if focal else 'unknown'}")
            print(f"    Benchmark:       {benchmark.ticker if benchmark else 'none'}")
            print(f"    Decision date:   {scenario.decision_at.date()}")
            print(f"    Status:          {scenario.status.value}")
            print(
                "    Target skills:   "
                + ", ".join(str(skill_id) for skill_id in scenario.primary_skill_ids)
            )


async def _view_scenario(service: HistoricalMarketScenarioService, learner_id: UUID, scenario_id: UUID) -> None:
    view = await service.get_learner_view(learner_id=learner_id, scenario_id=scenario_id)
    print("Scenario:")
    print(f"  Title:              {view.title}")
    print(f"  Instructions:       {view.learner_instructions}")
    print(f"  Prompt:             {view.prompt}")
    print(f"  Observation range:  {view.observation_start_at.date()} to {view.decision_at.date()}")
    print(f"  Data cutoff:        {view.data_cutoff_at}")
    print(f"  Focal security:     {view.focal_security.ticker}")
    print(f"  Benchmark:          {view.benchmark_security.ticker if view.benchmark_security else 'none'}")
    print("  Observation metrics:")
    print(f"    Observation return:  {view.observation_metrics.observation_return:.4f}")
    print(f"    Price change %:      {view.observation_metrics.price_change_percentage:.2f}%")
    if view.observation_metrics.annualized_volatility is not None:
        print(f"    Annualized volatility: {view.observation_metrics.annualized_volatility:.4f}")
    if view.observation_metrics.maximum_drawdown is not None:
        print(f"    Maximum drawdown:    {view.observation_metrics.maximum_drawdown:.4f}")
    print("  Options:")
    for option in view.exercise_options:
        print(f"    [{option.option_key}] {option.content}")
    print(f"  Chart bars: focal={len(view.focal_chart)}, benchmark={len(view.benchmark_chart)}")


async def _start_scenario(
    service: HistoricalMarketScenarioService, learner_id: UUID, scenario_id: UUID, attempt_id: UUID
) -> None:
    submission = await service.start_scenario(
        learner_id=learner_id, scenario_id=scenario_id, exercise_attempt_id=attempt_id
    )
    print("Submission started:")
    print(f"  Submission ID:  {submission.submission_id}")
    print(f"  Status:         {submission.status.value}")
    print(f"  Reveal status:  {submission.reveal_status.value}")


async def _submit_decision(
    service: HistoricalMarketScenarioService,
    submission_id: UUID,
    option_id: UUID,
    confidence: str | None,
    rationale: str | None,
) -> None:
    result = await service.submit_decision(
        submission_id=submission_id,
        selected_option_id=option_id,
        confidence_level=ConfidenceLevel(confidence) if confidence else None,
        learner_rationale=rationale,
    )
    submission = result.submission
    print("Decision submitted:")
    print(f"  Decision quality score: {submission.decision_quality_score:.4f}")
    print(f"  Decision quality:       {submission.decision_quality.value}")
    print(f"  Feedback:               {submission.feedback_text}")
    print(f"  Reveal available:       {result.reveal_available}")
    print("  Updated mastery:")
    for mastery in result.learning_activity_result.updated_mastery:
        print(f"    - skill {mastery.skill_id}: {mastery.mastery_score:.4f} ({mastery.mastery_level.value})")
    print("  (Mastery reflects decision quality only - the future market outcome is not yet known.)")


async def _reveal_outcome(service: HistoricalMarketScenarioService, submission_id: UUID) -> None:
    reveal = await service.reveal_outcome(submission_id=submission_id)
    outcome = reveal.outcome
    print("Outcome revealed:")
    print(f"  Focal future return:   {outcome.focal_return:.4f}")
    if outcome.benchmark_return is not None:
        print(f"  Benchmark return:      {outcome.benchmark_return:.4f}")
    if outcome.excess_return is not None:
        print(f"  Excess return:         {outcome.excess_return:.4f}")
    print(f"  Maximum upside:        {outcome.maximum_future_upside:.4f}")
    print(f"  Maximum drawdown:      {outcome.maximum_future_drawdown:.4f}")
    print(f"  Decision feedback:     {reveal.decision_feedback}")
    print(f"  Outcome feedback:      {reveal.outcome_feedback}")
    print(f"  Learning summary:      {reveal.combined_learning_summary}")
    print(
        f"  Mastery was already updated from decision quality ({reveal.mastery_score_used:.4f}), "
        "never from this realized market outcome."
    )


async def _validate_scenario(service: HistoricalMarketScenarioService, scenario_id: UUID) -> None:
    scenario = await service.validate_scenario(scenario_id=scenario_id)
    print(f"Scenario '{scenario.code}' is valid and ready (status={scenario.status.value}).")


async def _run(args: argparse.Namespace) -> int:
    has_action = any(
        [args.list_scenarios, args.view, args.start, args.submit, args.reveal, args.validate]
    )
    if not has_action:
        print(
            "error: specify one of --list, --view, --start, --submit, --reveal, or --validate",
            file=sys.stderr,
        )
        return 2

    def _parse_uuid(raw: str, label: str) -> UUID | None:
        try:
            return UUID(raw)
        except ValueError:
            print(f"error: '{raw}' is not a valid UUID for {label}", file=sys.stderr)
            return None

    settings = DatabaseSettings()
    engine = create_database_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        unit_of_work_factory = lambda: SqlAlchemyUnitOfWork(session_factory)  # noqa: E731
        service = _build_service(unit_of_work_factory)

        if args.list_scenarios:
            await _list_scenarios(unit_of_work_factory)

        if args.view:
            if args.learner_id is None or args.scenario_id is None:
                print("error: --view requires --learner-id and --scenario-id", file=sys.stderr)
                return 2
            learner_id = _parse_uuid(args.learner_id, "--learner-id")
            scenario_id = _parse_uuid(args.scenario_id, "--scenario-id")
            if learner_id is None or scenario_id is None:
                return 2
            await _view_scenario(service, learner_id, scenario_id)

        if args.start:
            if args.learner_id is None or args.scenario_id is None or args.attempt_id is None:
                print(
                    "error: --start requires --learner-id, --scenario-id, and --attempt-id",
                    file=sys.stderr,
                )
                return 2
            learner_id = _parse_uuid(args.learner_id, "--learner-id")
            scenario_id = _parse_uuid(args.scenario_id, "--scenario-id")
            attempt_id = _parse_uuid(args.attempt_id, "--attempt-id")
            if learner_id is None or scenario_id is None or attempt_id is None:
                return 2
            await _start_scenario(service, learner_id, scenario_id, attempt_id)

        if args.submit:
            if args.submission_id is None or args.option_id is None:
                print("error: --submit requires --submission-id and --option-id", file=sys.stderr)
                return 2
            submission_id = _parse_uuid(args.submission_id, "--submission-id")
            option_id = _parse_uuid(args.option_id, "--option-id")
            if submission_id is None or option_id is None:
                return 2
            await _submit_decision(service, submission_id, option_id, args.confidence, args.rationale)

        if args.reveal:
            if args.submission_id is None:
                print("error: --reveal requires --submission-id", file=sys.stderr)
                return 2
            submission_id = _parse_uuid(args.submission_id, "--submission-id")
            if submission_id is None:
                return 2
            await _reveal_outcome(service, submission_id)

        if args.validate:
            if args.scenario_id is None:
                print("error: --validate requires --scenario-id", file=sys.stderr)
                return 2
            scenario_id = _parse_uuid(args.scenario_id, "--scenario-id")
            if scenario_id is None:
                return 2
            await _validate_scenario(service, scenario_id)

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
