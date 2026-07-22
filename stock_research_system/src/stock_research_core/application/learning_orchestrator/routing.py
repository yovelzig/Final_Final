"""Deterministic route selection - `select_route` maps a classified
`LearningIntent` (plus already-loaded context, e.g. a scenario's reveal
status) to exactly one `LearningOrchestratorRoute`. Never asks an LLM to
choose a destination node; this is a pure function over already-known
state, used both by the `select_route` graph node
(`application.learning_orchestrator.nodes`) and directly by unit tests.
"""

from __future__ import annotations

from stock_research_core.domain.learning_orchestrator.enums import LearningIntent, LearningOrchestratorRoute

_DIRECT_ROUTE_BY_INTENT: dict[LearningIntent, LearningOrchestratorRoute] = {
    LearningIntent.EXPLAIN_CONCEPT: LearningOrchestratorRoute.GROUNDED_EXPLANATION,
    LearningIntent.LESSON_HELP: LearningOrchestratorRoute.LESSON_TUTOR,
    LearningIntent.EXERCISE_HELP: LearningOrchestratorRoute.EXERCISE_TUTOR,
    LearningIntent.REVIEW_PROGRESS: LearningOrchestratorRoute.PROGRESS_REFLECTION,
    LearningIntent.RECOMMEND_NEXT_LEARNING_ACTIVITY: LearningOrchestratorRoute.ADAPTIVE_RECOMMENDATION,
    LearningIntent.START_DAILY_PRACTICE: LearningOrchestratorRoute.PRACTICE_ACTION,
    LearningIntent.START_DIAGNOSTIC: LearningOrchestratorRoute.DIAGNOSTIC_ACTION,
    LearningIntent.SCENARIO_HELP_AFTER_REVEAL: LearningOrchestratorRoute.SCENARIO_AFTER_TUTOR,
    LearningIntent.PORTFOLIO_EXPLANATION: LearningOrchestratorRoute.PORTFOLIO_TUTOR,
    LearningIntent.GENERAL_TUTOR_CHAT: LearningOrchestratorRoute.GROUNDED_EXPLANATION,
    LearningIntent.UNKNOWN: LearningOrchestratorRoute.FALLBACK,
}

#: Scenario-submission `reveal_status` values (mirrors
#: `domain.market_scenarios.enums.ScenarioRevealStatus`, kept as plain
#: strings here so this module never imports the market-scenarios domain
#: package - routing only needs the string value already present in
#: loaded, bounded graph state).
_REVEALED_STATUS = "REVEALED"


def select_route(
    *, intent: LearningIntent, scenario_reveal_status: str | None = None,
) -> LearningOrchestratorRoute:
    """Pure, deterministic route selection. `scenario_reveal_status` is
    only consulted for `SCENARIO_HELP_BEFORE_DECISION`, since the
    classifier itself cannot know the learner's own submission state -
    `load_authorized_context` resolves it before this function runs, and
    a since-revealed scenario is redirected to the after-reveal tutor
    rather than ever presenting a stale "before decision" experience."""
    if intent == LearningIntent.SCENARIO_HELP_BEFORE_DECISION:
        if scenario_reveal_status == _REVEALED_STATUS:
            return LearningOrchestratorRoute.SCENARIO_AFTER_TUTOR
        return LearningOrchestratorRoute.SCENARIO_BEFORE_TUTOR

    return _DIRECT_ROUTE_BY_INTENT.get(intent, LearningOrchestratorRoute.FALLBACK)
