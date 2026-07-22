"""Application service orchestrating the historical market scenario engine.

This module depends only on domain models, application result models,
and `Protocol` contracts (`UnitOfWorkPort`, `ScenarioCalculatorPort`,
`ScenarioGradingPolicyPort`, `ExternallyGradedAnswerPort`). It never
instantiates a concrete engine, session, repository, or calculator, and
never calls `datetime.now()` directly - time comes from an injected
`clock` callable so tests are fully deterministic. It never calls
yfinance and never reads a `MarketBar` after the relevant cutoff.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable
from uuid import UUID

from stock_research_core.application.exceptions import (
    ExerciseAttemptNotFoundError,
    ExerciseNotFoundError,
    InactiveLearnerError,
    InvalidScenarioStateError,
    LearnerNotFoundError,
    MarketScenarioNotFoundError,
    ScenarioSubmissionNotFoundError,
    ScenarioValidationError,
)
from stock_research_core.application.market_scenarios.calculator import (
    OUTCOME_CALCULATION_VERSION,
    ScenarioCalculatorPort,
)
from stock_research_core.application.market_scenarios.grading import (
    GRADING_VERSION,
    ScenarioGradingPolicyPort,
)
from stock_research_core.application.market_scenarios.models import (
    LearnerSafeExerciseOption,
    LearnerScenarioView,
    ScenarioCatalogItem,
    ScenarioChartPoint,
    ScenarioReveal,
    ScenarioSubmissionResult,
)
from stock_research_core.application.market_scenarios.ports import ExternallyGradedAnswerPort
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.domain.learning.enums import ConfidenceLevel, ExerciseType
from stock_research_core.domain.learning.models import ExerciseAnswer
from stock_research_core.domain.market_scenarios.enums import (
    MarketScenarioStatus,
    MarketScenarioType,
    ScenarioRevealStatus,
    ScenarioSubmissionStatus,
)
from stock_research_core.domain.market_scenarios.models import (
    HistoricalMarketScenario,
    ScenarioOptionRubric,
    ScenarioSubmission,
)
from stock_research_core.domain.models import MarketBar, utc_now

Clock = Callable[[], datetime]

_DEFAULT_ESTIMATED_MINUTES = 10
#: A submission's `is_correct` flag (required by `ExerciseAttempt`) maps
#: to decision quality, never to realized outcome: GOOD or STRONG
#: decisions are "correct", matching the same 0.60 threshold this
#: module's grading policy uses for "good process".
_IS_CORRECT_MIN_SCORE = 0.60

#: A best-effort, documented safeguard against future-outcome language
#: leaking into learner-safe scenario content (spec section 14, item
#: 13). Not exhaustive - authors are still responsible for not writing
#: forward-looking language into scenario prompts/instructions.
_FUTURE_OUTCOME_PHRASES = (
    "will rise",
    "will fall",
    "later increased",
    "later decreased",
    "later rose",
    "later fell",
    "went on to",
    "eventually reached",
    "the stock ended up",
    "turned out to",
)


def _to_chart_point(bar: MarketBar) -> ScenarioChartPoint:
    return ScenarioChartPoint(
        timestamp=bar.timestamp,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        adjusted_close=bar.adjusted_close,
        volume=bar.volume,
    )


def _looks_like_future_outcome_text(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _FUTURE_OUTCOME_PHRASES)


class HistoricalMarketScenarioService:
    """Orchestrates scenario catalog browsing, point-in-time learner
    views, decision submission/grading, and post-grading reveal.
    """

    def __init__(
        self,
        unit_of_work_factory: Callable[[], UnitOfWorkPort],
        scenario_calculator: ScenarioCalculatorPort,
        scenario_grading_policy: ScenarioGradingPolicyPort,
        graded_answer_submitter: ExternallyGradedAnswerPort,
        clock: Clock = utc_now,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._scenario_calculator = scenario_calculator
        self._scenario_grading_policy = scenario_grading_policy
        self._graded_answer_submitter = graded_answer_submitter
        self._clock = clock

    # -- catalog ---------------------------------------------------------

    async def list_scenarios(
        self,
        *,
        skill_id: UUID | None = None,
        scenario_type: MarketScenarioType | None = None,
    ) -> list[ScenarioCatalogItem]:
        async with self._unit_of_work_factory() as uow:
            scenarios = await uow.market_scenarios.list_published(
                skill_id=skill_id, scenario_type=scenario_type
            )
            items: list[ScenarioCatalogItem] = []
            for scenario in scenarios:
                exercise = await uow.curriculum.get_exercise(scenario.exercise_id)
                if exercise is None:
                    continue
                profile = await uow.adaptive_profiles.get_by_exercise(scenario.exercise_id)
                estimated_minutes = (
                    max(1, round(profile.estimated_seconds / 60))
                    if profile is not None
                    else _DEFAULT_ESTIMATED_MINUTES
                )
                items.append(
                    ScenarioCatalogItem(
                        scenario_id=scenario.scenario_id,
                        title=scenario.title,
                        description=scenario.description,
                        scenario_type=scenario.scenario_type,
                        difficulty=exercise.difficulty,
                        primary_skill_ids=list(scenario.primary_skill_ids),
                        estimated_minutes=estimated_minutes,
                        published=scenario.status == MarketScenarioStatus.PUBLISHED,
                    )
                )
        return items

    # -- learner-safe view ---------------------------------------------------------

    async def get_learner_view(self, *, learner_id: UUID, scenario_id: UUID) -> LearnerScenarioView:
        async with self._unit_of_work_factory() as uow:
            learner = await uow.learners.get(learner_id)
            if learner is None:
                raise LearnerNotFoundError(f"No learner found with id '{learner_id}'.")
            if not learner.active:
                raise InactiveLearnerError(f"Learner '{learner_id}' is not active.")

            scenario = await uow.market_scenarios.get(scenario_id)
            if scenario is None or scenario.status != MarketScenarioStatus.PUBLISHED:
                raise MarketScenarioNotFoundError(f"No published scenario found with id '{scenario_id}'.")

            focal_security = await uow.securities.get_by_id(scenario.focal_security_id)
            if focal_security is None:
                raise MarketScenarioNotFoundError(
                    f"Focal security '{scenario.focal_security_id}' is not stored."
                )
            benchmark_security = None
            if scenario.benchmark_security_id is not None:
                benchmark_security = await uow.securities.get_by_id(scenario.benchmark_security_id)

            focal_bars = await uow.market_bars.list_range(
                scenario.focal_security_id,
                scenario.observation_start_at,
                scenario.decision_at,
                interval=scenario.interval,
                source_name=scenario.source_name,
            )
            benchmark_bars: list[MarketBar] = []
            if scenario.benchmark_security_id is not None:
                benchmark_bars = await uow.market_bars.list_range(
                    scenario.benchmark_security_id,
                    scenario.observation_start_at,
                    scenario.decision_at,
                    interval=scenario.interval,
                    source_name=scenario.source_name,
                )

            observation_metrics = await self._scenario_calculator.calculate_observation(
                scenario=scenario, focal_bars=focal_bars, benchmark_bars=benchmark_bars
            )

            options = await uow.curriculum.list_options(scenario.exercise_id)
            learner_safe_options = [
                LearnerSafeExerciseOption(
                    option_id=option.option_id,
                    option_key=option.option_key,
                    content=option.content,
                    position=option.position,
                )
                for option in options
            ]

        return LearnerScenarioView(
            scenario_id=scenario.scenario_id,
            exercise_id=scenario.exercise_id,
            title=scenario.title,
            description=scenario.description,
            scenario_type=scenario.scenario_type,
            focal_security=focal_security,
            benchmark_security=benchmark_security,
            observation_start_at=scenario.observation_start_at,
            decision_at=scenario.decision_at,
            data_cutoff_at=observation_metrics.data_cutoff_at,
            prompt=scenario.prompt,
            learner_instructions=scenario.learner_instructions,
            learning_objectives=list(scenario.learning_objectives),
            focal_chart=[_to_chart_point(bar) for bar in focal_bars],
            benchmark_chart=[_to_chart_point(bar) for bar in benchmark_bars],
            observation_metrics=observation_metrics,
            exercise_options=learner_safe_options,
            scenario_version=scenario.scenario_version,
        )

    # -- decision lifecycle ---------------------------------------------------------

    async def start_scenario(
        self, *, learner_id: UUID, scenario_id: UUID, exercise_attempt_id: UUID
    ) -> ScenarioSubmission:
        async with self._unit_of_work_factory() as uow:
            scenario = await uow.market_scenarios.get(scenario_id)
            if scenario is None:
                raise MarketScenarioNotFoundError(f"No scenario found with id '{scenario_id}'.")

            attempt = await uow.attempts.get_attempt(exercise_attempt_id)
            if attempt is None:
                raise ExerciseAttemptNotFoundError(
                    f"No exercise attempt found with id '{exercise_attempt_id}'."
                )
            if attempt.learner_id != learner_id:
                raise InvalidScenarioStateError("attempt does not belong to the requesting learner")
            if attempt.exercise_id != scenario.exercise_id:
                raise InvalidScenarioStateError(
                    "attempt's exercise does not match the scenario's exercise"
                )

            existing = await uow.scenario_submissions.get_by_attempt(exercise_attempt_id)
            if existing is not None:
                return existing  # idempotent: never duplicate a submission for one attempt

            rubrics = await uow.scenario_rubrics.list_for_scenario(scenario_id)
            if not rubrics:
                raise InvalidScenarioStateError(f"Scenario '{scenario_id}' has no option rubrics yet.")

            submission = ScenarioSubmission(
                scenario_id=scenario_id,
                learner_id=learner_id,
                exercise_attempt_id=exercise_attempt_id,
                reveal_status=ScenarioRevealStatus.HIDDEN,
                rubric_version=rubrics[0].rubric_version,
            )
            created = await uow.scenario_submissions.create(submission)
            await uow.commit()
        return created

    async def submit_decision(
        self,
        *,
        submission_id: UUID,
        selected_option_id: UUID,
        confidence_level: ConfidenceLevel | None = None,
        learner_rationale: str | None = None,
    ) -> ScenarioSubmissionResult:
        now = self._clock()
        async with self._unit_of_work_factory() as uow:
            submission = await uow.scenario_submissions.get(submission_id)
            if submission is None:
                raise ScenarioSubmissionNotFoundError(f"No scenario submission found with id '{submission_id}'.")
            if submission.status != ScenarioSubmissionStatus.STARTED:
                raise InvalidScenarioStateError(
                    f"submission '{submission_id}' is '{submission.status.value}', expected STARTED"
                )

            scenario = await uow.market_scenarios.get(submission.scenario_id)
            if scenario is None:
                raise MarketScenarioNotFoundError(f"No scenario found with id '{submission.scenario_id}'.")
            exercise = await uow.curriculum.get_exercise(scenario.exercise_id)
            if exercise is None:
                raise ExerciseNotFoundError(f"No exercise found with id '{scenario.exercise_id}'.")

            options = await uow.curriculum.list_options(exercise.exercise_id)
            if selected_option_id not in {option.option_id for option in options}:
                raise InvalidScenarioStateError(
                    "selected_option_id does not belong to this scenario's exercise"
                )

            rubric = await uow.scenario_rubrics.get_for_option(scenario.scenario_id, selected_option_id)
            if rubric is None:
                raise InvalidScenarioStateError(f"No rubric found for option '{selected_option_id}'.")

            score, decision_quality, feedback_codes, feedback_text = self._scenario_grading_policy.grade(
                scenario=scenario,
                rubric=rubric,
                confidence_level=confidence_level,
                learner_rationale=learner_rationale,
            )

            answer = ExerciseAnswer(
                attempt_id=submission.exercise_attempt_id, selected_option_ids=[selected_option_id]
            )
            learning_activity_result = await self._graded_answer_submitter.submit_externally_graded_answer(
                attempt_id=submission.exercise_attempt_id,
                answer=answer,
                normalized_score=score,
                is_correct=score >= _IS_CORRECT_MIN_SCORE,
                grading_version=GRADING_VERSION,
            )

            graded_submission = submission.model_copy(
                update={
                    "status": ScenarioSubmissionStatus.GRADED,
                    "selected_option_id": selected_option_id,
                    "confidence_level": confidence_level,
                    "learner_rationale": learner_rationale,
                    "decision_quality_score": score,
                    "decision_quality": decision_quality,
                    "feedback_codes": feedback_codes,
                    "feedback_text": feedback_text,
                    "reveal_status": ScenarioRevealStatus.AVAILABLE,
                    "submitted_at": now,
                    "graded_at": now,
                    "rubric_version": rubric.rubric_version,
                    "updated_at": now,
                }
            )
            stored_submission = await uow.scenario_submissions.update(graded_submission)
            await uow.commit()

        return ScenarioSubmissionResult(
            submission=stored_submission,
            learning_activity_result=learning_activity_result,
            reveal_available=True,
        )

    async def reveal_outcome(self, *, submission_id: UUID) -> ScenarioReveal:
        now = self._clock()
        async with self._unit_of_work_factory() as uow:
            submission = await uow.scenario_submissions.get(submission_id)
            if submission is None:
                raise ScenarioSubmissionNotFoundError(f"No scenario submission found with id '{submission_id}'.")
            if submission.status not in (ScenarioSubmissionStatus.GRADED, ScenarioSubmissionStatus.REVEALED):
                raise InvalidScenarioStateError(
                    f"submission '{submission_id}' must be GRADED before it can be revealed"
                )

            scenario = await uow.market_scenarios.get(submission.scenario_id)
            if scenario is None:
                raise MarketScenarioNotFoundError(f"No scenario found with id '{submission.scenario_id}'.")
            assert submission.selected_option_id is not None
            rubric = await uow.scenario_rubrics.get_for_option(
                scenario.scenario_id, submission.selected_option_id
            )
            if rubric is None:
                raise InvalidScenarioStateError(
                    f"No rubric found for option '{submission.selected_option_id}'."
                )

            focal_bars = await uow.market_bars.list_range(
                scenario.focal_security_id,
                scenario.decision_at,
                scenario.reveal_end_at,
                interval=scenario.interval,
                source_name=scenario.source_name,
            )
            benchmark_bars: list[MarketBar] = []
            if scenario.benchmark_security_id is not None:
                benchmark_bars = await uow.market_bars.list_range(
                    scenario.benchmark_security_id,
                    scenario.decision_at,
                    scenario.reveal_end_at,
                    interval=scenario.interval,
                    source_name=scenario.source_name,
                )

            already_revealed = submission.status == ScenarioSubmissionStatus.REVEALED
            if already_revealed:
                outcome = await uow.scenario_outcomes.get(
                    scenario.scenario_id, submission.outcome_calculation_version
                )
                if outcome is None:
                    raise InvalidScenarioStateError(
                        f"Revealed submission '{submission_id}' has no matching stored outcome."
                    )
            else:
                outcome = await uow.scenario_outcomes.get(scenario.scenario_id, OUTCOME_CALCULATION_VERSION)
                if outcome is None:
                    outcome = await self._scenario_calculator.calculate_outcome(
                        scenario=scenario, focal_bars=focal_bars, benchmark_bars=benchmark_bars
                    )
                    outcome = await uow.scenario_outcomes.upsert(outcome)

            alignment = self._scenario_grading_policy.calculate_outcome_alignment(
                rubric=rubric, outcome=outcome
            )
            submission_with_alignment = submission.model_copy(
                update={"outcome_alignment_score": alignment}
            )
            decision_feedback, outcome_feedback, combined_summary = (
                self._scenario_grading_policy.build_reveal_feedback(
                    submission=submission_with_alignment, rubric=rubric, outcome=outcome
                )
            )

            assert submission.decision_quality_score is not None
            total_display_score = round(0.5 * submission.decision_quality_score + 0.5 * alignment, 6)

            if already_revealed:
                stored_submission = submission_with_alignment.model_copy(
                    update={"total_display_score": total_display_score}
                )
            else:
                stored_submission = await uow.scenario_submissions.update(
                    submission_with_alignment.model_copy(
                        update={
                            "status": ScenarioSubmissionStatus.REVEALED,
                            "reveal_status": ScenarioRevealStatus.REVEALED,
                            "total_display_score": total_display_score,
                            "revealed_at": now,
                            "outcome_calculation_version": outcome.calculation_version,
                            "updated_at": now,
                        }
                    )
                )
                await uow.commit()

        assert stored_submission.decision_quality_score is not None
        # `list_range` is inclusive on both ends, so `focal_bars`/`benchmark_bars`
        # (queried over [decision_at, reveal_end_at]) still contain the decision
        # bar itself - excluded here so no chart point at or before decision_at
        # is ever exposed as "future" data.
        return ScenarioReveal(
            scenario=scenario,
            submission=stored_submission,
            outcome=outcome,
            future_focal_chart=[
                _to_chart_point(bar) for bar in focal_bars if bar.timestamp > scenario.decision_at
            ],
            future_benchmark_chart=[
                _to_chart_point(bar) for bar in benchmark_bars if bar.timestamp > scenario.decision_at
            ],
            decision_feedback=decision_feedback,
            outcome_feedback=outcome_feedback,
            combined_learning_summary=combined_summary,
            mastery_score_used=stored_submission.decision_quality_score,
        )

    async def get_reveal(self, *, submission_id: UUID) -> ScenarioReveal:
        async with self._unit_of_work_factory() as uow:
            submission = await uow.scenario_submissions.get(submission_id)
            if submission is None:
                raise ScenarioSubmissionNotFoundError(f"No scenario submission found with id '{submission_id}'.")
            if submission.status != ScenarioSubmissionStatus.REVEALED:
                raise InvalidScenarioStateError(f"submission '{submission_id}' has not been revealed yet")
        return await self.reveal_outcome(submission_id=submission_id)

    # -- adaptive-engine eligibility ---------------------------------------------------------

    async def is_exercise_eligible(self, exercise_id: UUID) -> bool:
        """Structurally satisfies `adaptive_learning.ports.ScenarioEligibilityPort`
        without importing it (Protocols are structural)."""
        async with self._unit_of_work_factory() as uow:
            scenario = await uow.market_scenarios.get_by_exercise_id(exercise_id)
            if scenario is None or scenario.status != MarketScenarioStatus.PUBLISHED:
                return False

            options = await uow.curriculum.list_options(exercise_id)
            if not options:
                return False
            rubrics = await uow.scenario_rubrics.list_for_scenario(scenario.scenario_id)
            rubric_option_ids = {rubric.exercise_option_id for rubric in rubrics}
            if not all(option.option_id in rubric_option_ids for option in options):
                return False

            focal_security = await uow.securities.get_by_id(scenario.focal_security_id)
            if focal_security is None:
                return False

            observation_bars = await uow.market_bars.list_range(
                scenario.focal_security_id,
                scenario.observation_start_at,
                scenario.decision_at,
                interval=scenario.interval,
                source_name=scenario.source_name,
            )
            if len(observation_bars) < scenario.minimum_observation_bars:
                return False

            reveal_bars = await uow.market_bars.list_range(
                scenario.focal_security_id,
                scenario.decision_at,
                scenario.reveal_end_at,
                interval=scenario.interval,
                source_name=scenario.source_name,
            )
            reveal_bar_count = sum(1 for bar in reveal_bars if bar.timestamp > scenario.decision_at)
            return reveal_bar_count >= scenario.minimum_reveal_bars

    async def get_scenario_for_exercise(self, exercise_id: UUID) -> HistoricalMarketScenario | None:
        """Used by `MarketScenarioLearningOrchestrator` to resolve the
        scenario linked to an adaptive-recommended exercise."""
        async with self._unit_of_work_factory() as uow:
            return await uow.market_scenarios.get_by_exercise_id(exercise_id)

    async def get_submission_for_attempt(self, exercise_attempt_id: UUID) -> ScenarioSubmission | None:
        """Used by `MarketScenarioLearningOrchestrator`, which only ever
        has an `exercise_attempt_id` (from the adaptive session
        activity), never a `submission_id` directly."""
        async with self._unit_of_work_factory() as uow:
            return await uow.scenario_submissions.get_by_attempt(exercise_attempt_id)

    # -- administrative creation and validation ---------------------------------------------------------

    async def create_or_update_scenario(
        self, *, scenario: HistoricalMarketScenario, rubrics: list[ScenarioOptionRubric]
    ) -> HistoricalMarketScenario:
        now = self._clock()
        async with self._unit_of_work_factory() as uow:
            await self._validate_scenario_data(uow, scenario=scenario, rubrics=rubrics)

            stored_scenario = await uow.market_scenarios.upsert(
                scenario.model_copy(update={"status": MarketScenarioStatus.DRAFT, "updated_at": now})
            )
            rewritten_rubrics = [
                rubric.model_copy(update={"scenario_id": stored_scenario.scenario_id}) for rubric in rubrics
            ]
            await uow.scenario_rubrics.upsert_many(rewritten_rubrics)

            stored_scenario = await uow.market_scenarios.set_status(
                stored_scenario.scenario_id, MarketScenarioStatus.READY
            )
            if scenario.status == MarketScenarioStatus.PUBLISHED:
                stored_scenario = await uow.market_scenarios.set_status(
                    stored_scenario.scenario_id, MarketScenarioStatus.PUBLISHED
                )

            await uow.commit()
        return stored_scenario

    async def validate_scenario(self, *, scenario_id: UUID) -> HistoricalMarketScenario:
        """Re-runs the same validation `create_or_update_scenario` uses
        against an already-stored scenario, without mutating anything -
        the read-only counterpart used by the CLI's `--validate` flag.
        Raises `ScenarioValidationError` (with an explanatory message,
        never a stack trace) if the scenario is not currently valid.
        """
        async with self._unit_of_work_factory() as uow:
            scenario = await uow.market_scenarios.get(scenario_id)
            if scenario is None:
                raise MarketScenarioNotFoundError(f"No scenario found with id '{scenario_id}'.")
            rubrics = await uow.scenario_rubrics.list_for_scenario(scenario_id)
            await self._validate_scenario_data(uow, scenario=scenario, rubrics=rubrics)
        return scenario

    async def _validate_scenario_data(
        self, uow: UnitOfWorkPort, *, scenario: HistoricalMarketScenario, rubrics: list[ScenarioOptionRubric]
    ) -> None:
        exercise = await uow.curriculum.get_exercise(scenario.exercise_id)
        if exercise is None:
            raise ScenarioValidationError(f"Exercise '{scenario.exercise_id}' does not exist.")
        if exercise.exercise_type != ExerciseType.SCENARIO_DECISION:
            raise ScenarioValidationError("The linked exercise must be of type SCENARIO_DECISION.")

        options = await uow.curriculum.list_options(exercise.exercise_id)
        option_ids = {option.option_id for option in options}
        rubric_option_ids = {rubric.exercise_option_id for rubric in rubrics}
        if len(rubrics) != len(options) or rubric_option_ids != option_ids:
            raise ScenarioValidationError(
                "Every exercise option must have exactly one rubric, and no rubric may "
                "reference an option outside the exercise."
            )

        focal_security = await uow.securities.get_by_id(scenario.focal_security_id)
        if focal_security is None:
            raise ScenarioValidationError(f"Focal security '{scenario.focal_security_id}' does not exist.")
        if scenario.benchmark_security_id is not None:
            benchmark_security = await uow.securities.get_by_id(scenario.benchmark_security_id)
            if benchmark_security is None:
                raise ScenarioValidationError(
                    f"Benchmark security '{scenario.benchmark_security_id}' does not exist."
                )

        observation_bars = await uow.market_bars.list_range(
            scenario.focal_security_id,
            scenario.observation_start_at,
            scenario.decision_at,
            interval=scenario.interval,
            source_name=scenario.source_name,
        )
        if len(observation_bars) < scenario.minimum_observation_bars:
            raise ScenarioValidationError(
                f"Only {len(observation_bars)} observation bars are stored; "
                f"{scenario.minimum_observation_bars} are required."
            )
        if not any(bar.timestamp <= scenario.decision_at for bar in observation_bars):
            raise ScenarioValidationError("decision_at does not fall on or after any stored trading bar.")

        reveal_bars = await uow.market_bars.list_range(
            scenario.focal_security_id,
            scenario.decision_at,
            scenario.reveal_end_at,
            interval=scenario.interval,
            source_name=scenario.source_name,
        )
        reveal_bar_count = sum(1 for bar in reveal_bars if bar.timestamp > scenario.decision_at)
        if reveal_bar_count < scenario.minimum_reveal_bars:
            raise ScenarioValidationError(
                f"Only {reveal_bar_count} future reveal bars are stored; "
                f"{scenario.minimum_reveal_bars} are required."
            )

        if scenario.benchmark_security_id is not None:
            benchmark_observation_bars = await uow.market_bars.list_range(
                scenario.benchmark_security_id,
                scenario.observation_start_at,
                scenario.decision_at,
                interval=scenario.interval,
                source_name=scenario.source_name,
            )
            if len(benchmark_observation_bars) < scenario.minimum_observation_bars:
                raise ScenarioValidationError("Insufficient stored benchmark bars over the observation window.")

        for text in (scenario.title, scenario.description, scenario.prompt, scenario.learner_instructions):
            if _looks_like_future_outcome_text(text):
                raise ScenarioValidationError(
                    "Learner-safe scenario content must not describe the future outcome."
                )
