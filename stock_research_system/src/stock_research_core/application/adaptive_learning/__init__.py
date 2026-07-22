"""Adaptive learning engine use cases: result models, policy/repository
ports, deterministic policies, `AdaptiveLearningService`, and the
`AdaptiveLearningOrchestrator`.

`AdaptiveLearningService` and `AdaptiveLearningOrchestrator` are
intentionally not re-exported here: `service.py` imports
`stock_research_core.application.persistence.ports` (for
`UnitOfWorkPort`), which in turn imports
`stock_research_core.application.adaptive_learning.ports` - eagerly
importing `service` from this package's `__init__.py` would make that
a circular import (the same issue already solved for
`application.learning` in Phase 4). Import them directly:
`from stock_research_core.application.adaptive_learning.service import AdaptiveLearningService`
`from stock_research_core.application.adaptive_learning.orchestrator import AdaptiveLearningOrchestrator`
"""

from stock_research_core.application.adaptive_learning.models import (
    AdaptiveLearnerState,
    DiagnosticSummary,
    ExerciseCandidate,
    ExerciseRecommendation,
    SessionSummary,
)
from stock_research_core.application.adaptive_learning.policies import (
    COMPONENT_WEIGHTS,
    DeterministicReviewSchedulingPolicy,
    RuleBasedAdaptivePolicy,
    RuleBasedDiagnosticPolicy,
    RuleBasedDifficultyPolicy,
)

__all__ = [
    "COMPONENT_WEIGHTS",
    "AdaptiveLearnerState",
    "DeterministicReviewSchedulingPolicy",
    "DiagnosticSummary",
    "ExerciseCandidate",
    "ExerciseRecommendation",
    "RuleBasedAdaptivePolicy",
    "RuleBasedDiagnosticPolicy",
    "RuleBasedDifficultyPolicy",
    "SessionSummary",
]
