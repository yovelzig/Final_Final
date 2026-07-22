"""Application-level repository contracts for the historical market
scenario engine, plus the narrow `ExternallyGradedAnswerPort`.

Pure `Protocol` definitions - no SQLAlchemy (or any other infrastructure
library) is imported here. Concrete repository implementations live
under `stock_research_core.infrastructure.database`.

A few lookup methods are not in the spec's literal bullet list but are
required for the service/orchestrator to locate what they operate on -
the same "necessary, minimal addition" pattern already used throughout
this codebase (e.g. `AttemptRepositoryPort.get_attempt`,
`LearningSessionRepositoryPort.get_activity_by_decision`):
`MarketScenarioRepositoryPort.get_by_exercise_id`,
`ScenarioSubmissionRepositoryPort.get_by_attempt`.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from stock_research_core.application.learning.models import LearningActivityResult
from stock_research_core.domain.learning.models import ExerciseAnswer
from stock_research_core.domain.market_scenarios.enums import (
    MarketScenarioStatus,
    MarketScenarioType,
)
from stock_research_core.domain.market_scenarios.models import (
    HistoricalMarketScenario,
    ScenarioGenerationRun,
    ScenarioOptionRubric,
    ScenarioOutcome,
    ScenarioSubmission,
)


class MarketScenarioRepositoryPort(Protocol):
    """Persists and queries `HistoricalMarketScenario` objects."""

    async def upsert(self, scenario: HistoricalMarketScenario) -> HistoricalMarketScenario: ...

    async def get(self, scenario_id: UUID) -> HistoricalMarketScenario | None: ...

    async def get_by_code(self, code: str) -> HistoricalMarketScenario | None: ...

    async def get_by_exercise_id(self, exercise_id: UUID) -> HistoricalMarketScenario | None: ...

    async def list_published(
        self,
        skill_id: UUID | None = None,
        scenario_type: MarketScenarioType | None = None,
    ) -> list[HistoricalMarketScenario]: ...

    async def set_status(
        self, scenario_id: UUID, status: MarketScenarioStatus
    ) -> HistoricalMarketScenario: ...


class ScenarioRubricRepositoryPort(Protocol):
    """Persists and queries `ScenarioOptionRubric` objects."""

    async def upsert_many(self, rubrics: list[ScenarioOptionRubric]) -> int: ...

    async def get_for_option(
        self, scenario_id: UUID, exercise_option_id: UUID
    ) -> ScenarioOptionRubric | None: ...

    async def list_for_scenario(self, scenario_id: UUID) -> list[ScenarioOptionRubric]: ...


class ScenarioOutcomeRepositoryPort(Protocol):
    """Persists and queries `ScenarioOutcome` objects."""

    async def upsert(self, outcome: ScenarioOutcome) -> ScenarioOutcome: ...

    async def get(
        self, scenario_id: UUID, calculation_version: str | None = None
    ) -> ScenarioOutcome | None: ...


class ScenarioSubmissionRepositoryPort(Protocol):
    """Persists and queries `ScenarioSubmission` objects.

    Unique per `exercise_attempt_id` - `create` must reject a second
    active submission for the same attempt (enforced by the database
    unique constraint and, defensively, by the service layer).
    """

    async def create(self, submission: ScenarioSubmission) -> ScenarioSubmission: ...

    async def get(self, submission_id: UUID) -> ScenarioSubmission | None: ...

    async def get_by_attempt(self, exercise_attempt_id: UUID) -> ScenarioSubmission | None: ...

    async def update(self, submission: ScenarioSubmission) -> ScenarioSubmission: ...

    async def list_for_learner(self, learner_id: UUID) -> list[ScenarioSubmission]: ...


class ScenarioGenerationRunRepositoryPort(Protocol):
    """Creates and updates `ScenarioGenerationRun` audit records."""

    async def create(self, run: ScenarioGenerationRun) -> ScenarioGenerationRun: ...

    async def mark_completed(
        self,
        run_id: UUID,
        *,
        observation_bars_found: int,
        reveal_bars_found: int,
        benchmark_bars_found: int,
    ) -> ScenarioGenerationRun: ...

    async def mark_failed(
        self, run_id: UUID, *, error_type: str, error_message: str
    ) -> ScenarioGenerationRun: ...

    async def mark_insufficient_data(
        self,
        run_id: UUID,
        *,
        observation_bars_found: int,
        reveal_bars_found: int,
        benchmark_bars_found: int,
    ) -> ScenarioGenerationRun: ...

    async def get(self, run_id: UUID) -> ScenarioGenerationRun | None: ...

    async def list_recent(self, limit: int = 10) -> list[ScenarioGenerationRun]: ...


class ExternallyGradedAnswerPort(Protocol):
    """The narrow shape of `LearningService.submit_externally_graded_answer`
    that `HistoricalMarketScenarioService` depends on.

    `HistoricalMarketScenarioService` never imports `LearningService`
    directly (Protocols are structural, so `LearningService` satisfies
    this without importing it either) - the concrete instance is wired
    together only in the composition root (the CLI), keeping the
    scenario grading/mastery flow reused, never duplicated.
    """

    async def submit_externally_graded_answer(
        self,
        *,
        attempt_id: UUID,
        answer: ExerciseAnswer,
        normalized_score: float,
        is_correct: bool,
        grading_version: str,
    ) -> LearningActivityResult: ...
