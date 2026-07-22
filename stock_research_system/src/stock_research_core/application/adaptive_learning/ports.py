"""Application-level Protocols for the adaptive learning engine.

Pure `Protocol` definitions - no SQLAlchemy (or any other infrastructure
library) is imported here. Policy protocols describe *what* an adaptive
decision-making component does; concrete rule-based implementations
live in `policies.py`, and a future ML-based policy can implement the
same Protocols without changing `AdaptiveLearningService`. Repository
protocols describe persistence; concrete implementations live under
`stock_research_core.infrastructure.database`.

A few lookup-by-id methods (`LearningSessionRepositoryPort.get_activity`
/ `get_activity_by_decision`, `DiagnosticRepositoryPort.get_item`) are
not explicitly itemized in the original spec bullet list but are
required for the service to locate the activity/item it is updating -
the same pattern already used for `AttemptRepositoryPort.get_attempt`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from stock_research_core.application.adaptive_learning.models import (
    AdaptiveLearnerState,
    DiagnosticSummary,
    ExerciseCandidate,
)
from stock_research_core.domain.adaptive_learning.models import (
    AdaptiveDecision,
    DiagnosticAssessment,
    DiagnosticAssessmentItem,
    ExerciseAdaptiveProfile,
    LearningSession,
    LearningSessionActivity,
    SkillReviewSchedule,
)
from stock_research_core.domain.adaptive_learning.enums import DifficultyAdjustment
from stock_research_core.domain.learning.enums import ConfidenceLevel


class AdaptivePolicyPort(Protocol):
    """Decides what a learner should practice next."""

    policy_version: str

    async def recommend(
        self,
        *,
        state: AdaptiveLearnerState,
        candidates: list[ExerciseCandidate],
        now: datetime,
    ) -> AdaptiveDecision: ...


class DifficultyPolicyPort(Protocol):
    """Recommends a target difficulty score for the next exercise."""

    policy_version: str

    def recommend_difficulty(
        self,
        *,
        mastery_score: float,
        recent_correct_rate: float | None,
        consecutive_correct: int,
        consecutive_incorrect: int,
        confidence_level: ConfidenceLevel | None,
    ) -> tuple[float, DifficultyAdjustment]: ...


class ReviewSchedulingPolicyPort(Protocol):
    """Computes the next `SkillReviewSchedule` after a graded practice.

    `learner_id`/`skill_id` are not in the original spec signature but
    are required to construct a brand-new `SkillReviewSchedule` when
    `previous` is `None` - the same kind of necessary, minimal addition
    already used for `MasteryCalculatorPort.update` in Phase 4.
    """

    policy_version: str

    def update_schedule(
        self,
        *,
        learner_id: UUID,
        skill_id: UUID,
        previous: SkillReviewSchedule | None,
        normalized_score: float,
        confidence_level: ConfidenceLevel | None,
        practiced_at: datetime,
    ) -> SkillReviewSchedule: ...


class DiagnosticPolicyPort(Protocol):
    """Selects diagnostic items and summarizes diagnostic results."""

    policy_version: str

    async def select_items(
        self,
        *,
        learner_id: UUID,
        skill_ids: list[UUID],
        candidates: list[ExerciseCandidate],
        maximum_items: int,
        now: datetime,
    ) -> list[DiagnosticAssessmentItem]: ...

    def summarize(
        self,
        *,
        assessment: DiagnosticAssessment,
        items: list[DiagnosticAssessmentItem],
    ) -> DiagnosticSummary: ...


class AdaptiveProfileRepositoryPort(Protocol):
    """Persists and queries `ExerciseAdaptiveProfile` objects."""

    async def upsert(self, profile: ExerciseAdaptiveProfile) -> ExerciseAdaptiveProfile: ...

    async def get_by_exercise(self, exercise_id: UUID) -> ExerciseAdaptiveProfile | None: ...

    async def list_active(
        self, diagnostic_only: bool = False, review_only: bool = False
    ) -> list[ExerciseAdaptiveProfile]: ...


class LearningSessionRepositoryPort(Protocol):
    """Persists and queries `LearningSession` and `LearningSessionActivity` objects."""

    async def create_session(self, session: LearningSession) -> LearningSession: ...

    async def get_session(self, session_id: UUID) -> LearningSession | None: ...

    async def update_session(self, session: LearningSession) -> LearningSession: ...

    async def list_active_sessions(self, learner_id: UUID) -> list[LearningSession]: ...

    async def add_activity(self, activity: LearningSessionActivity) -> LearningSessionActivity: ...

    async def get_activity(self, activity_id: UUID) -> LearningSessionActivity | None: ...

    async def get_activity_by_decision(
        self, decision_id: UUID
    ) -> LearningSessionActivity | None: ...

    async def update_activity(self, activity: LearningSessionActivity) -> LearningSessionActivity: ...

    async def list_activities(self, session_id: UUID) -> list[LearningSessionActivity]: ...


class DiagnosticRepositoryPort(Protocol):
    """Persists and queries `DiagnosticAssessment` and `DiagnosticAssessmentItem` objects."""

    async def create_assessment(self, assessment: DiagnosticAssessment) -> DiagnosticAssessment: ...

    async def get_assessment(self, assessment_id: UUID) -> DiagnosticAssessment | None: ...

    async def update_assessment(self, assessment: DiagnosticAssessment) -> DiagnosticAssessment: ...

    async def save_items(self, items: list[DiagnosticAssessmentItem]) -> int: ...

    async def get_item(self, item_id: UUID) -> DiagnosticAssessmentItem | None: ...

    async def update_item(self, item: DiagnosticAssessmentItem) -> DiagnosticAssessmentItem: ...

    async def list_items(self, assessment_id: UUID) -> list[DiagnosticAssessmentItem]: ...

    async def list_recent_assessments(
        self, learner_id: UUID, limit: int = 10
    ) -> list[DiagnosticAssessment]: ...


class ReviewScheduleRepositoryPort(Protocol):
    """Persists and queries `SkillReviewSchedule` objects. Unique per (learner, skill)."""

    async def upsert(self, schedule: SkillReviewSchedule) -> SkillReviewSchedule: ...

    async def get(self, learner_id: UUID, skill_id: UUID) -> SkillReviewSchedule | None: ...

    async def list_for_learner(self, learner_id: UUID) -> list[SkillReviewSchedule]: ...

    async def list_due(self, learner_id: UUID, as_of: datetime) -> list[SkillReviewSchedule]: ...


class ScenarioEligibilityPort(Protocol):
    """Decides whether a `SCENARIO_DECISION` exercise is currently
    eligible for adaptive recommendation (published scenario, every
    option rubric present, sufficient stored bars - see
    `HistoricalMarketScenarioService.is_exercise_eligible`, which
    structurally satisfies this Protocol without importing it).

    Kept in the adaptive-learning application package, not imported
    from `application.market_scenarios`, so the adaptive engine stays
    fully decoupled from the scenario feature - the same "no import of
    `domain.learning`" independence already used by `domain.
    adaptive_learning`. The concrete instance is wired together only in
    the composition root (the CLI).
    """

    async def is_eligible(self, exercise_id: UUID) -> bool: ...


class AdaptiveDecisionRepositoryPort(Protocol):
    """Persists and queries `AdaptiveDecision` audit records."""

    async def create_decision(self, decision: AdaptiveDecision) -> AdaptiveDecision: ...

    async def get_decision(self, decision_id: UUID) -> AdaptiveDecision | None: ...

    async def update_decision(self, decision: AdaptiveDecision) -> AdaptiveDecision: ...

    async def list_recent_decisions(
        self, learner_id: UUID, limit: int = 10
    ) -> list[AdaptiveDecision]: ...

    async def list_session_decisions(self, session_id: UUID) -> list[AdaptiveDecision]: ...
