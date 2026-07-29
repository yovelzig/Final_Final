"""Unit tests for `RuleBasedTutorGuardrail`'s Phase G2E2A Hebrew-language
parameters (`language`, `apply_topic_vocabulary_check`).

Mirrors `test_tutor_guardrails.py`'s fixtures. These tests exercise the
guardrail directly, in isolation from `GroundedAITutorService` (which has
its own defense-in-depth-merge tests in `test_ai_tutor_service_hebrew.py`).
"""

from __future__ import annotations

import re
from uuid import uuid4

import pytest

from stock_research_core.application.ai_tutor.guardrails import (
    RuleBasedTutorGuardrail,
    more_restrictive_decision,
)
from stock_research_core.application.ai_tutor.models import TutorContext
from stock_research_core.application.language.enums import DetectedLanguage
from stock_research_core.domain.ai_tutor.enums import TutorContextType, TutorGuardrailAction, TutorMessageRole
from stock_research_core.domain.ai_tutor.models import (
    EXACT_ADVICE_REFUSAL,
    EXACT_ADVICE_REFUSAL_HE,
    EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
    EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE,
    EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL,
    EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL_HE,
    TutorMessage,
)


def _message(text: str) -> TutorMessage:
    return TutorMessage(conversation_id=uuid4(), role=TutorMessageRole.USER, content=text)


def _general_context() -> TutorContext:
    return TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=uuid4())


def _scenario_before_context() -> TutorContext:
    return TutorContext(
        context_type=TutorContextType.SCENARIO_BEFORE_DECISION, learner_id=uuid4(), scenario_id=uuid4(),
    )


class TestEnglishDefaultsUnchanged:
    """`language`/`apply_topic_vocabulary_check` both default to their
    pre-Phase-G2E2A-equivalent values - every call site that doesn't
    pass them (i.e. every pre-existing call site) must behave exactly
    as `test_tutor_guardrails.py` already proves."""

    def test_default_language_is_english_for_refusal_text(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        decision = guardrail.evaluate_input(
            conversation_id=uuid4(), message=_message("should I buy NVDA now?"), context=_general_context()
        )
        assert decision.safe_response_override == EXACT_ADVICE_REFUSAL

    def test_default_applies_topic_vocabulary_check(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        decision = guardrail.evaluate_input(
            conversation_id=uuid4(),
            message=_message("Can you recommend a good pizza restaurant near me?"),
            context=_general_context(),
        )
        assert decision.action == TutorGuardrailAction.FALLBACK
        assert decision.safe_response_override == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK


class TestHebrewLocalizedSafetyText:
    def test_guaranteed_return_english_ticker_embedded_in_hebrew_refuses_with_hebrew_text(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        message = _message("יש לי strategy שבה I can't lose money, זה נכון?")
        decision = guardrail.evaluate_input(
            conversation_id=uuid4(), message=message, context=_general_context(),
            language=DetectedLanguage.HE, apply_topic_vocabulary_check=False,
        )
        assert decision.action == TutorGuardrailAction.REFUSE
        assert decision.safe_response_override == EXACT_ADVICE_REFUSAL_HE

    def test_buy_sell_english_ticker_embedded_in_hebrew_refuses_with_hebrew_text(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        message = _message("האם כדאי לי לבצע buy NVDA עכשיו?")
        decision = guardrail.evaluate_input(
            conversation_id=uuid4(), message=message, context=_general_context(),
            language=DetectedLanguage.HE, apply_topic_vocabulary_check=False,
        )
        assert decision.action == TutorGuardrailAction.REFUSE
        assert decision.request_category.value == "BUY_SELL_REQUEST"
        assert decision.safe_response_override == EXACT_ADVICE_REFUSAL_HE

    def test_scenario_future_information_request_in_hebrew_context_uses_hebrew_text(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        message = _message("what happens next in this scenario?")
        decision = guardrail.evaluate_input(
            conversation_id=uuid4(), message=message, context=_scenario_before_context(),
            language=DetectedLanguage.HE, apply_topic_vocabulary_check=False,
        )
        assert decision.action == TutorGuardrailAction.REFUSE
        assert decision.safe_response_override == EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL_HE

    def test_off_topic_fallback_in_hebrew_uses_hebrew_text_when_check_applied(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        message = _message("what time is it")  # translated-English stand-in, no finance vocabulary
        decision = guardrail.evaluate_input(
            conversation_id=uuid4(), message=message, context=_general_context(),
            language=DetectedLanguage.HE, apply_topic_vocabulary_check=True,
        )
        assert decision.action == TutorGuardrailAction.FALLBACK
        assert decision.safe_response_override == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE


class TestApplyTopicVocabularyCheckFlag:
    def test_original_hebrew_text_with_check_disabled_never_falls_back_on_topic_grounds(self) -> None:
        """A genuinely on-topic Hebrew question (no English finance
        vocabulary at all) must not be misclassified as off-topic - the
        English-only vocabulary check has zero signal for Hebrew script
        and must be skipped for the original-text pass."""
        guardrail = RuleBasedTutorGuardrail()
        message = _message("מה זה פיזור סיכונים בתיק השקעות?")
        decision = guardrail.evaluate_input(
            conversation_id=uuid4(), message=message, context=_general_context(),
            language=DetectedLanguage.HE, apply_topic_vocabulary_check=False,
        )
        assert decision.action == TutorGuardrailAction.ALLOW

    def test_same_hebrew_text_with_check_enabled_still_reports_no_signal_as_off_topic(self) -> None:
        """Confirms the flag is actually load-bearing: the very same
        Hebrew text, if the check *were* applied, has zero `[a-z]`
        tokens and is misclassified as off-topic - this is exactly the
        failure mode `apply_topic_vocabulary_check=False` exists to
        avoid for the original-text pass."""
        guardrail = RuleBasedTutorGuardrail()
        message = _message("מה זה פיזור סיכונים בתיק השקעות?")
        decision = guardrail.evaluate_input(
            conversation_id=uuid4(), message=message, context=_general_context(),
            language=DetectedLanguage.HE, apply_topic_vocabulary_check=True,
            apply_hebrew_topic_vocabulary_check=False,
        )
        assert decision.action == TutorGuardrailAction.FALLBACK


_PURE_HEBREW_BUY_SELL = "איזו מניה כדאי לי לקנות?"
_PURE_HEBREW_GUARANTEED_RETURN = "תבטיח לי תשואה"
_PURE_HEBREW_PERSONALIZED_ALLOCATION = "כמה מהכסף שלי להשקיע במניה הזאת?"
_PURE_HEBREW_SCENARIO_FUTURE = "תגלה לי מה קורה בהמשך התרחיש"

_ALL_PURE_HEBREW_UNSAFE_REQUESTS = (
    _PURE_HEBREW_BUY_SELL,
    _PURE_HEBREW_GUARANTEED_RETURN,
    _PURE_HEBREW_PERSONALIZED_ALLOCATION,
    _PURE_HEBREW_SCENARIO_FUTURE,
)


class TestPureHebrewSafetyWithNoEnglishTriggerWords:
    """Phase G2E2A req. 4: the deterministic guardrail must classify an
    unsafe request from the learner's OWN Hebrew words.

    Every phrase here is pure Hebrew - `test_every_phrase_is_pure_hebrew`
    proves there is not a single Latin character to lean on - so none of
    these can be caught by the English `buy`/`sell`/`guarantee` patterns.
    This is what makes the safety layer independent of translation: if the
    translation provider is down, an unsafe Hebrew request is still
    refused rather than reaching a model."""

    @pytest.mark.parametrize("text", _ALL_PURE_HEBREW_UNSAFE_REQUESTS)
    def test_every_phrase_is_pure_hebrew(self, text: str) -> None:
        assert not re.search(r"[A-Za-z]", text), (
            "this suite is only meaningful if the phrase carries no English trigger word"
        )

    def test_hebrew_buy_sell_request_is_refused(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        decision = guardrail.evaluate_input(
            conversation_id=uuid4(), message=_message(_PURE_HEBREW_BUY_SELL), context=_general_context(),
            language=DetectedLanguage.HE, apply_topic_vocabulary_check=False,
        )
        assert decision.action == TutorGuardrailAction.REFUSE
        assert decision.request_category.value == "BUY_SELL_REQUEST"
        assert decision.matched_rule_codes == ["BUY_SELL_INSTRUCTION"]
        assert decision.safe_response_override == EXACT_ADVICE_REFUSAL_HE

    def test_hebrew_guaranteed_return_request_is_refused(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        decision = guardrail.evaluate_input(
            conversation_id=uuid4(), message=_message(_PURE_HEBREW_GUARANTEED_RETURN),
            context=_general_context(), language=DetectedLanguage.HE, apply_topic_vocabulary_check=False,
        )
        assert decision.action == TutorGuardrailAction.REFUSE
        assert decision.request_category.value == "GUARANTEED_RETURN_REQUEST"
        assert decision.matched_rule_codes == ["GUARANTEED_RETURN"]
        assert decision.safe_response_override == EXACT_ADVICE_REFUSAL_HE

    def test_hebrew_personalized_allocation_request_gets_the_educational_boundary(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        decision = guardrail.evaluate_input(
            conversation_id=uuid4(), message=_message(_PURE_HEBREW_PERSONALIZED_ALLOCATION),
            context=_general_context(), language=DetectedLanguage.HE, apply_topic_vocabulary_check=False,
        )
        assert decision.action == TutorGuardrailAction.ALLOW_WITH_BOUNDARY
        assert decision.request_category.value == "PERSONALIZED_INVESTMENT_ADVICE"
        assert decision.matched_rule_codes == ["PERSONALIZED_ALLOCATION"]
        assert decision.safe_response_override is not None
        assert decision.safe_response_override.startswith(EXACT_ADVICE_REFUSAL_HE)

    def test_hebrew_scenario_future_information_request_is_refused(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        decision = guardrail.evaluate_input(
            conversation_id=uuid4(), message=_message(_PURE_HEBREW_SCENARIO_FUTURE),
            context=_scenario_before_context(), language=DetectedLanguage.HE,
            apply_topic_vocabulary_check=False,
        )
        assert decision.action == TutorGuardrailAction.REFUSE
        assert decision.matched_rule_codes == ["SCENARIO_FUTURE_INFORMATION_REQUEST"]
        assert decision.safe_response_override == EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL_HE

    @pytest.mark.parametrize("text", _ALL_PURE_HEBREW_UNSAFE_REQUESTS)
    def test_no_unsafe_hebrew_request_is_ever_plainly_allowed(self, text: str) -> None:
        """The category-by-category assertions above pin the exact
        outcome; this one guards the property that actually matters - no
        phrase in this set may reach a model unbounded.

        Evaluated in the scenario-before-decision context, which is the
        only one where all four categories apply: asking what happens next
        is a safety violation *because* an undecided scenario's outcome
        must not leak, so outside a scenario that same question is an
        ordinary (non-refusable) one and is deliberately allowed."""
        guardrail = RuleBasedTutorGuardrail()
        decision = guardrail.evaluate_input(
            conversation_id=uuid4(), message=_message(text), context=_scenario_before_context(),
            language=DetectedLanguage.HE, apply_topic_vocabulary_check=False,
        )
        assert decision.action != TutorGuardrailAction.ALLOW

    def test_the_scenario_future_phrase_is_only_refused_inside_a_scenario(self) -> None:
        """Documents the one context-dependent category, so the bound
        above is not mistaken for a claim that this phrase is unsafe
        everywhere."""
        guardrail = RuleBasedTutorGuardrail()
        decision = guardrail.evaluate_input(
            conversation_id=uuid4(), message=_message(_PURE_HEBREW_SCENARIO_FUTURE),
            context=_general_context(), language=DetectedLanguage.HE,
            apply_topic_vocabulary_check=False,
        )
        assert decision.action == TutorGuardrailAction.ALLOW

    @pytest.mark.parametrize("text", _ALL_PURE_HEBREW_UNSAFE_REQUESTS)
    def test_classification_does_not_depend_on_the_language_parameter(self, text: str) -> None:
        """`language` selects the localized refusal *text* only - it must
        never change which rule fires, so a caller that mis-detects the
        language still gets the same safety decision."""
        guardrail = RuleBasedTutorGuardrail()
        contexts = (_general_context(), _scenario_before_context())
        for context in contexts:
            hebrew = guardrail.evaluate_input(
                conversation_id=uuid4(), message=_message(text), context=context,
                language=DetectedLanguage.HE, apply_topic_vocabulary_check=False,
            )
            english = guardrail.evaluate_input(
                conversation_id=uuid4(), message=_message(text), context=context,
                language=DetectedLanguage.EN, apply_topic_vocabulary_check=False,
            )
            assert hebrew.action == english.action
            assert hebrew.request_category == english.request_category
            assert hebrew.matched_rule_codes == english.matched_rule_codes


class TestEnglishClassificationUnaffectedByHebrewPatterns:
    """The Hebrew pattern groups are Hebrew-script-only, so they cannot
    match Latin text at all - an on-topic English question must still be
    plainly allowed."""

    @pytest.mark.parametrize(
        "text",
        [
            "What is diversification in a portfolio?",
            "Can you explain how compounding affects long-term returns?",
            "How is volatility measured for an index fund?",
        ],
    )
    def test_on_topic_english_questions_are_still_allowed(self, text: str) -> None:
        guardrail = RuleBasedTutorGuardrail()
        decision = guardrail.evaluate_input(
            conversation_id=uuid4(), message=_message(text), context=_general_context()
        )
        assert decision.action == TutorGuardrailAction.ALLOW
        assert decision.matched_rule_codes == []


class TestMoreRestrictiveDecisionNeverDowngrades:
    """The merge used for translated-text defense in depth (req. 4): the
    more restrictive decision always wins, and an original-text REFUSE can
    never be talked down by a translation that looks innocuous."""

    def _decide(self, text: str, *, context: TutorContext) -> object:
        return RuleBasedTutorGuardrail().evaluate_input(
            conversation_id=uuid4(), message=_message(text), context=context,
            language=DetectedLanguage.HE, apply_topic_vocabulary_check=False,
        )

    def test_original_hebrew_refuse_survives_a_benign_translation(self) -> None:
        context = _general_context()
        original = self._decide(_PURE_HEBREW_BUY_SELL, context=context)
        benign_translation = self._decide("What is diversification?", context=context)

        merged = more_restrictive_decision(original, benign_translation)

        assert merged.action == TutorGuardrailAction.REFUSE
        assert merged is original

    def test_a_benign_original_is_escalated_by_an_unsafe_translation(self) -> None:
        """The other direction: a Hebrew phrasing the Hebrew patterns miss
        can still be caught once it is translated to English."""
        context = _general_context()
        original = self._decide("מה המצב עם המניה הזאת?", context=context)
        unsafe_translation = self._decide("should I buy NVDA now?", context=context)

        merged = more_restrictive_decision(original, unsafe_translation)

        assert merged.action == TutorGuardrailAction.REFUSE
        assert merged is unsafe_translation

    def test_merging_two_identical_decisions_prefers_the_original(self) -> None:
        context = _general_context()
        original = self._decide(_PURE_HEBREW_GUARANTEED_RETURN, context=context)
        translated = self._decide("guarantee me a return", context=context)

        merged = more_restrictive_decision(original, translated)

        assert merged is original
        assert merged.action == TutorGuardrailAction.REFUSE


class TestValidateOutputRejectsPureHebrewUnsafeAnswers:
    """`validate_output` re-checks the model's own answer text: a Hebrew
    answer that hands out a buy/sell instruction, claims a guaranteed
    return, or leaks a scenario outcome must be flagged even though it
    contains no English trigger word."""

    def test_hebrew_buy_sell_instruction_in_an_answer_is_flagged(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        _status, issues = guardrail.validate_output(
            answer_text="כדאי לך לקנות עכשיו את המניה הזאת.", cited_chunk_ids=[],
            retrieved_candidates=[], context=_general_context(),
        )
        assert "DIRECT_BUY_SELL_INSTRUCTION" in issues

    def test_hebrew_guaranteed_return_claim_in_an_answer_is_flagged(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        _status, issues = guardrail.validate_output(
            answer_text="אני מבטיח לך תשואה של 12% בשנה.", cited_chunk_ids=[],
            retrieved_candidates=[], context=_general_context(),
        )
        assert "GUARANTEED_RETURN_CLAIM" in issues

    def test_hebrew_scenario_outcome_leak_in_an_answer_is_flagged(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        _status, issues = guardrail.validate_output(
            answer_text="בהמשך התרחיש המניה עלתה בחדות.", cited_chunk_ids=[],
            retrieved_candidates=[], context=_scenario_before_context(),
        )
        assert "SCENARIO_FUTURE_INFORMATION_LEAK" in issues

    def test_a_grounded_hebrew_explanation_is_not_flagged(self) -> None:
        """Regression guard against over-matching: an ordinary Hebrew
        explanation must stay clean, or the Hebrew patterns would make
        every Hebrew answer unusable."""
        guardrail = RuleBasedTutorGuardrail()
        _status, issues = guardrail.validate_output(
            answer_text="פיזור סיכונים הוא חלוקת ההשקעות בין נכסים שונים כדי להקטין תנודתיות.",
            cited_chunk_ids=[], retrieved_candidates=[], context=_general_context(),
        )
        assert issues == []


class TestValidateOutputAcceptsHebrewApprovedStrings:
    def test_hebrew_fallback_text_is_not_flagged_insufficient_evidence(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        status, issues = guardrail.validate_output(
            answer_text=EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE, cited_chunk_ids=[], retrieved_candidates=[],
            context=_general_context(),
        )
        assert "INSUFFICIENT_EVIDENCE" not in [status.value]
        assert status.value == "PARTIALLY_GROUNDED" or status.value == "GROUNDED"

    def test_hebrew_advice_refusal_text_is_not_flagged_insufficient_evidence(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        status, _issues = guardrail.validate_output(
            answer_text=EXACT_ADVICE_REFUSAL_HE, cited_chunk_ids=[], retrieved_candidates=[],
            context=_general_context(),
        )
        assert status.value != "INSUFFICIENT_EVIDENCE"

    def test_arbitrary_uncited_hebrew_text_is_still_flagged_insufficient_evidence(self) -> None:
        guardrail = RuleBasedTutorGuardrail()
        status, _issues = guardrail.validate_output(
            answer_text="זהו טקסט שרירותי שאינו אחד המחרוזות המאושרות.", cited_chunk_ids=[],
            retrieved_candidates=[], context=_general_context(),
        )
        assert status.value == "INSUFFICIENT_EVIDENCE"
