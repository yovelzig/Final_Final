"""Unit tests for `application.learning_orchestrator.routing.select_route` -
a pure function, no I/O."""

from __future__ import annotations

import pytest

from stock_research_core.application.learning_orchestrator.routing import select_route
from stock_research_core.domain.learning_orchestrator.enums import LearningIntent, LearningOrchestratorRoute


@pytest.mark.parametrize(
    "intent,expected_route",
    [
        (LearningIntent.EXPLAIN_CONCEPT, LearningOrchestratorRoute.GROUNDED_EXPLANATION),
        (LearningIntent.LESSON_HELP, LearningOrchestratorRoute.LESSON_TUTOR),
        (LearningIntent.EXERCISE_HELP, LearningOrchestratorRoute.EXERCISE_TUTOR),
        (LearningIntent.REVIEW_PROGRESS, LearningOrchestratorRoute.PROGRESS_REFLECTION),
        (LearningIntent.RECOMMEND_NEXT_LEARNING_ACTIVITY, LearningOrchestratorRoute.ADAPTIVE_RECOMMENDATION),
        (LearningIntent.START_DAILY_PRACTICE, LearningOrchestratorRoute.PRACTICE_ACTION),
        (LearningIntent.START_DIAGNOSTIC, LearningOrchestratorRoute.DIAGNOSTIC_ACTION),
        (LearningIntent.SCENARIO_HELP_AFTER_REVEAL, LearningOrchestratorRoute.SCENARIO_AFTER_TUTOR),
        (LearningIntent.PORTFOLIO_EXPLANATION, LearningOrchestratorRoute.PORTFOLIO_TUTOR),
        (LearningIntent.GENERAL_TUTOR_CHAT, LearningOrchestratorRoute.GROUNDED_EXPLANATION),
        (LearningIntent.UNKNOWN, LearningOrchestratorRoute.FALLBACK),
    ],
)
def test_direct_intent_to_route_mapping(intent: LearningIntent, expected_route: LearningOrchestratorRoute) -> None:
    assert select_route(intent=intent) == expected_route


def test_scenario_before_decision_routes_to_before_tutor_by_default() -> None:
    route = select_route(intent=LearningIntent.SCENARIO_HELP_BEFORE_DECISION)
    assert route == LearningOrchestratorRoute.SCENARIO_BEFORE_TUTOR


def test_scenario_before_decision_routes_to_before_tutor_when_not_revealed() -> None:
    route = select_route(intent=LearningIntent.SCENARIO_HELP_BEFORE_DECISION, scenario_reveal_status="PENDING")
    assert route == LearningOrchestratorRoute.SCENARIO_BEFORE_TUTOR


def test_scenario_before_decision_redirects_to_after_tutor_once_revealed() -> None:
    """The classifier itself cannot know the learner's own submission
    state - once `load_authorized_context` has resolved a REVEALED
    submission, routing must never present a stale before-decision
    experience."""
    route = select_route(intent=LearningIntent.SCENARIO_HELP_BEFORE_DECISION, scenario_reveal_status="REVEALED")
    assert route == LearningOrchestratorRoute.SCENARIO_AFTER_TUTOR


def test_scenario_reveal_status_is_ignored_for_other_intents() -> None:
    route = select_route(intent=LearningIntent.EXPLAIN_CONCEPT, scenario_reveal_status="REVEALED")
    assert route == LearningOrchestratorRoute.GROUNDED_EXPLANATION


def test_every_learning_intent_has_a_defined_route() -> None:
    for intent in LearningIntent:
        route = select_route(intent=intent)
        assert isinstance(route, LearningOrchestratorRoute)
