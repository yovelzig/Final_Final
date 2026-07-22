"""Unit tests for `RuleBasedLearningIntentClassifier` - deterministic,
no external call, no randomness."""

from __future__ import annotations

from uuid import uuid4

import pytest

from stock_research_core.application.learning_orchestrator.intent import RuleBasedLearningIntentClassifier
from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.domain.learning_orchestrator.enums import IntentClassificationMethod, LearningIntent

classifier = RuleBasedLearningIntentClassifier()


async def _classify(text: str, *, context_references: dict | None = None) -> LearningIntent:
    result = await classifier.classify(
        learner_id=uuid4(), user_input=text, context_type=TutorContextType.GENERAL_EDUCATION,
        context_references=context_references or {},
    )
    return result.intent


@pytest.mark.parametrize(
    "phrase,expected_intent",
    [
        ("give me a diagnostic assessment", LearningIntent.START_DIAGNOSTIC),
        ("test my financial knowledge", LearningIntent.START_DIAGNOSTIC),
        ("let's start a practice session", LearningIntent.START_DAILY_PRACTICE),
        ("give me a short quick practice", LearningIntent.START_DAILY_PRACTICE),
        ("how am I doing so far?", LearningIntent.REVIEW_PROGRESS),
        ("what are my weak skills", LearningIntent.REVIEW_PROGRESS),
        ("what should I study next", LearningIntent.RECOMMEND_NEXT_LEARNING_ACTIVITY),
        ("what do you recommend for me", LearningIntent.RECOMMEND_NEXT_LEARNING_ACTIVITY),
        ("tell me about my portfolio concentration", LearningIntent.PORTFOLIO_EXPLANATION),
        ("explain diversification to me", LearningIntent.EXPLAIN_CONCEPT),
        ("what is compound interest", LearningIntent.EXPLAIN_CONCEPT),
    ],
)
async def test_classifies_phrase_without_context_requirements(phrase: str, expected_intent: LearningIntent) -> None:
    assert await _classify(phrase) == expected_intent


async def test_scenario_help_requires_scenario_id_context() -> None:
    # Without scenario_id in context, the SCENARIO_HELP rule is skipped -
    # "scenario" is still finance vocabulary, so this falls through to the
    # general-chat fallback rather than a scenario-specific route.
    assert await _classify("help me decide on this scenario") == LearningIntent.GENERAL_TUTOR_CHAT
    assert (
        await _classify("help me decide on this scenario", context_references={"scenario_id": uuid4()})
        == LearningIntent.SCENARIO_HELP_BEFORE_DECISION
    )


async def test_exercise_help_requires_exercise_id_context() -> None:
    assert await _classify("help with this exercise") == LearningIntent.GENERAL_TUTOR_CHAT
    assert (
        await _classify("help with this exercise", context_references={"exercise_id": uuid4()})
        == LearningIntent.EXERCISE_HELP
    )


async def test_lesson_help_requires_lesson_id_context() -> None:
    # "help me understand this lesson" also matches the general
    # CONCEPT_EXPLANATION_PHRASE rule ("help me understand") when the
    # lesson-specific rule is skipped for lacking lesson_id context.
    assert await _classify("help me understand this lesson") == LearningIntent.EXPLAIN_CONCEPT
    assert (
        await _classify("help me understand this lesson", context_references={"lesson_id": uuid4()})
        == LearningIntent.LESSON_HELP
    )


@pytest.mark.parametrize(
    "phrase",
    [
        "should I buy Apple stock?",
        "what should I buy right now",
        "which stock should I buy",
        "how many shares should I buy",
        "is this a guaranteed return?",
        "risk-free profit opportunity",
        "is this a sure thing",
    ],
)
async def test_investment_advice_phrases_always_route_to_unknown(phrase: str) -> None:
    result = await classifier.classify(
        learner_id=uuid4(), user_input=phrase, context_type=TutorContextType.GENERAL_EDUCATION, context_references={},
    )
    assert result.intent == LearningIntent.UNKNOWN
    assert result.matched_rule_codes == ["INVESTMENT_ADVICE_BOUNDARY"]
    assert result.requires_action_approval is False


async def test_investment_advice_check_runs_before_any_other_rule() -> None:
    """Phrasing that could plausibly also match another rule (e.g.
    contains 'explain') must still hit the safety boundary first."""
    result = await classifier.classify(
        learner_id=uuid4(), user_input="should I buy or sell, please explain what to buy",
        context_type=TutorContextType.GENERAL_EDUCATION, context_references={},
    )
    assert result.intent == LearningIntent.UNKNOWN
    assert result.matched_rule_codes == ["INVESTMENT_ADVICE_BOUNDARY"]


async def test_finance_vocabulary_without_specific_rule_falls_back_to_general_chat() -> None:
    result = await classifier.classify(
        learner_id=uuid4(), user_input="I've been thinking about interest rates lately",
        context_type=TutorContextType.GENERAL_EDUCATION, context_references={},
    )
    assert result.intent == LearningIntent.GENERAL_TUTOR_CHAT


async def test_unrelated_small_talk_is_unknown_not_general_chat() -> None:
    result = await classifier.classify(
        learner_id=uuid4(), user_input="what a nice day it is today",
        context_type=TutorContextType.GENERAL_EDUCATION, context_references={},
    )
    assert result.intent == LearningIntent.UNKNOWN


async def test_classification_is_deterministic() -> None:
    text = "what should I study next"
    first = await classifier.classify(
        learner_id=uuid4(), user_input=text, context_type=TutorContextType.GENERAL_EDUCATION, context_references={}
    )
    second = await classifier.classify(
        learner_id=uuid4(), user_input=text, context_type=TutorContextType.GENERAL_EDUCATION, context_references={}
    )
    assert first.intent == second.intent
    assert first.matched_rule_codes == second.matched_rule_codes


async def test_classification_reports_rule_based_method_and_version() -> None:
    result = await classifier.classify(
        learner_id=uuid4(), user_input="what is diversification", context_type=TutorContextType.GENERAL_EDUCATION,
        context_references={},
    )
    assert result.method == IntentClassificationMethod.RULE_BASED
    assert result.classifier_version == classifier.classifier_version
    assert result.classifier_version == "learning-intent-rules-v1"
