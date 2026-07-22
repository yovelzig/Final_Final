"""Deterministic, rule-based learner-intent classification -
`RuleBasedLearningIntentClassifier` (version `learning-intent-rules-v1`),
the default and primary classifier. An optional single-call
model-assisted fallback lives in
`infrastructure.learning_orchestrator.optional_model_intent_classifier`
and is only ever consulted when this classifier returns `UNKNOWN` and
`LANGGRAPH_MODEL_INTENT_CLASSIFICATION=true`.

Investment-advice/buy-sell/guaranteed-return phrasing is checked FIRST
and always short-circuits to `UNKNOWN` with `requires_action_approval=False`
- this classifier never produces an intent that could route to a
portfolio action. The real, exact-text safety boundary is the existing
`RuleBasedTutorGuardrail`, evaluated *before* intent classification even
runs in the graph (`evaluate_input_guardrail` precedes `classify_intent`
in the topology) - this is defense in depth, not a replacement for it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.domain.learning_orchestrator.enums import IntentClassificationMethod, LearningIntent
from stock_research_core.domain.learning_orchestrator.models import IntentClassification

CLASSIFIER_VERSION = "learning-intent-rules-v1"

_GROUNDED_TUTOR_INTENTS = frozenset(
    {
        LearningIntent.EXPLAIN_CONCEPT, LearningIntent.LESSON_HELP, LearningIntent.EXERCISE_HELP,
        LearningIntent.REVIEW_PROGRESS, LearningIntent.SCENARIO_HELP_BEFORE_DECISION,
        LearningIntent.SCENARIO_HELP_AFTER_REVEAL, LearningIntent.PORTFOLIO_EXPLANATION,
        LearningIntent.GENERAL_TUTOR_CHAT,
    }
)
_ACTION_APPROVAL_INTENTS = frozenset({LearningIntent.START_DAILY_PRACTICE, LearningIntent.START_DIAGNOSTIC})


@dataclass(frozen=True)
class _Rule:
    code: str
    intent: LearningIntent
    pattern: re.Pattern[str]
    requires_context_key: str | None = None


def _p(*phrases: str) -> re.Pattern[str]:
    return re.compile("|".join(re.escape(phrase) for phrase in phrases), re.IGNORECASE)


# Checked first, in isolation - never combined with the ordered rule list
# below, so nothing can accidentally rank an educational rule ahead of
# this safety check.
_INVESTMENT_ADVICE_PATTERN = re.compile(
    r"\b(should i (buy|sell)|what (should|do) i buy|what to buy|which (stock|stocks|security|securities) "
    r"(to|should i) buy|how many shares (should|do) i (buy|sell)|guarantee(d)? (a )?return|"
    r"risk[- ]free (return|profit)|sure (thing|bet)|can'?t lose)\b",
    re.IGNORECASE,
)

# Ordered: first match wins. Order encodes priority when phrasing could
# plausibly match more than one category (e.g. "test my knowledge on
# diversification" should route to diagnostic, not concept-explanation).
_RULES: tuple[_Rule, ...] = (
    _Rule("DIAGNOSTIC_PHRASE", LearningIntent.START_DIAGNOSTIC, _p(
        "diagnostic assessment", "diagnostic test", "test my financial knowledge", "test my knowledge",
        "give me a diagnostic", "assess my knowledge", "assess my financial knowledge",
    )),
    _Rule("DAILY_PRACTICE_PHRASE", LearningIntent.START_DAILY_PRACTICE, _p(
        "start practice", "start a practice", "daily practice", "practice session", "short practice",
        "practice for", "quick practice", "give me a short",
    )),
    _Rule("PROGRESS_REVIEW_PHRASE", LearningIntent.REVIEW_PROGRESS, _p(
        "how am i doing", "review my progress", "my progress", "weak skills", "why do i keep making mistakes",
        "why do i keep getting", "what are my weak", "how is my progress", "check my progress",
    )),
    _Rule("RECOMMEND_NEXT_PHRASE", LearningIntent.RECOMMEND_NEXT_LEARNING_ACTIVITY, _p(
        "what should i study next", "what should i learn next", "what should i study", "what should i learn",
        "what next", "recommend", "what do you recommend",
    )),
    _Rule("SCENARIO_HELP_PHRASE", LearningIntent.SCENARIO_HELP_BEFORE_DECISION, _p(
        "this scenario", "the scenario", "historical scenario", "reason through this scenario",
        "help me with this scenario", "help me decide",
    ), requires_context_key="scenario_id"),
    _Rule("PORTFOLIO_EXPLANATION_PHRASE", LearningIntent.PORTFOLIO_EXPLANATION, _p(
        "my portfolio", "portfolio concentration", "diversification score", "concentrated", "my holdings",
        "my risk assessment",
    )),
    _Rule("EXERCISE_HELP_PHRASE", LearningIntent.EXERCISE_HELP, _p(
        "this exercise", "this question", "this problem", "help with this exercise", "hint",
    ), requires_context_key="exercise_id"),
    _Rule("LESSON_HELP_PHRASE", LearningIntent.LESSON_HELP, _p(
        "this lesson", "in this lesson", "help me understand this lesson",
    ), requires_context_key="lesson_id"),
    _Rule("CONCEPT_EXPLANATION_PHRASE", LearningIntent.EXPLAIN_CONCEPT, _p(
        "what is", "what are", "explain", "how does", "how do", "define", "definition of", "help me understand",
    )),
)

#: A light-touch check for whether the input even looks finance/education
#: related, so completely unrelated small talk falls to UNKNOWN rather
#: than being force-classified as GENERAL_TUTOR_CHAT.
_FINANCE_EDUCATION_VOCABULARY = re.compile(
    r"\b(stock|stocks|market|portfolio|invest|diversif|risk|return|interest|compound|bond|etf|fund|"
    r"asset|dividend|volatility|inflation|budget|saving|save|finance|financial|economy|economic|"
    r"exercise|lesson|skill|mastery|scenario|drawdown|allocation)\b",
    re.IGNORECASE,
)


class RuleBasedLearningIntentClassifier:
    """The default, deterministic intent classifier. Same input always
    produces the same classification (no randomness, no external call)."""

    classifier_version = CLASSIFIER_VERSION

    async def classify(
        self,
        *,
        learner_id: UUID,
        user_input: str,
        context_type: TutorContextType,
        context_references: dict[str, UUID],
    ) -> IntentClassification:
        text = user_input.strip()

        if _INVESTMENT_ADVICE_PATTERN.search(text):
            return IntentClassification(
                intent=LearningIntent.UNKNOWN, confidence=1.0, method=IntentClassificationMethod.RULE_BASED,
                context_references=context_references, matched_rule_codes=["INVESTMENT_ADVICE_BOUNDARY"],
                requires_grounded_tutor=False, requires_action_approval=False,
                classifier_version=self.classifier_version,
            )

        for rule in _RULES:
            if rule.requires_context_key is not None and rule.requires_context_key not in context_references:
                continue
            if rule.pattern.search(text):
                intent = rule.intent
                return IntentClassification(
                    intent=intent, confidence=0.9, method=IntentClassificationMethod.RULE_BASED,
                    context_references=context_references, matched_rule_codes=[rule.code],
                    requires_grounded_tutor=intent in _GROUNDED_TUTOR_INTENTS,
                    requires_action_approval=intent in _ACTION_APPROVAL_INTENTS,
                    classifier_version=self.classifier_version,
                )

        if _FINANCE_EDUCATION_VOCABULARY.search(text):
            return IntentClassification(
                intent=LearningIntent.GENERAL_TUTOR_CHAT, confidence=0.5, method=IntentClassificationMethod.RULE_BASED,
                context_references=context_references, matched_rule_codes=["FINANCE_VOCABULARY_FALLBACK"],
                requires_grounded_tutor=True, requires_action_approval=False,
                classifier_version=self.classifier_version,
            )

        return IntentClassification(
            intent=LearningIntent.UNKNOWN, confidence=0.0, method=IntentClassificationMethod.RULE_BASED,
            context_references=context_references, matched_rule_codes=[],
            requires_grounded_tutor=False, requires_action_approval=False,
            classifier_version=self.classifier_version,
        )
