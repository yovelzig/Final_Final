"""Unit tests for `GraphNodes`'s Phase G2E2A Hebrew localization -
`evaluate_input_guardrail`, `build_refusal_response`, and
`build_fallback_response` sourcing their text from the shared
`LanguageServicePort` rather than a hard-coded English copy.

Mirrors `test_orchestrator_nodes.py`'s fixtures.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.ai_tutor.guardrails import RuleBasedTutorGuardrail
from stock_research_core.application.exceptions import LanguageServiceError
from stock_research_core.application.language.enums import DetectedLanguage, LocalizedMessageKey
from stock_research_core.application.language.localization import localize
from stock_research_core.application.language.models import TranslationResult
from stock_research_core.application.language.unavailable_language_service import UnavailableLanguageService
from stock_research_core.application.learning_orchestrator.intent import RuleBasedLearningIntentClassifier
from stock_research_core.application.learning_orchestrator.nodes import (
    GraphNodes,
    NodeDependencies,
    prepared_language_from_state,
)
from stock_research_core.application.learning_orchestrator.state import new_state
from stock_research_core.domain.ai_tutor.models import (
    EXACT_ADVICE_REFUSAL_HE,
    EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
    EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE,
)
from stock_research_core.domain.learning_orchestrator.enums import LearningIntent, LearningOrchestratorRoute

from tests.unit.learning_orchestrator_fakes import FakeUnitOfWork

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_HEBREW_QUESTION = "מה זה פיזור סיכונים בתיק השקעות?"


def _uow_factory():
    uow = FakeUnitOfWork()
    return lambda: uow


class FakeLanguageService(UnavailableLanguageService):
    """A translation-capable stand-in: `detect_language`/`localize` are
    inherited (they are the real, pure implementations), and only
    `translate_to_english_query` - the single network-touching method of a
    real adapter - is scripted.

    `translations` maps an exact Hebrew input to the canned bounded
    English query a real provider would return; anything unmapped falls
    back to `default_query`. `raise_error=True` reproduces an unavailable
    provider.
    """

    def __init__(
        self,
        *,
        translations: dict[str, str] | None = None,
        default_query: str = "diversification portfolio risk",
        raise_error: bool = False,
    ) -> None:
        self._translations = translations or {}
        self._default_query = default_query
        self._raise_error = raise_error
        self.translate_calls: list[str] = []

    async def translate_to_english_query(self, text: str, *, source_language: DetectedLanguage) -> TranslationResult:
        self.translate_calls.append(text)
        if self._raise_error:
            raise LanguageServiceError("translation unavailable (test)")
        return TranslationResult(
            translated_query=self._translations.get(text, self._default_query),
            source_language=source_language, translation_policy_version="test-v1",
        )


def _nodes(*, language_service_enabled: bool = True, language_service=None) -> GraphNodes:
    deps = NodeDependencies(
        unit_of_work_factory=_uow_factory(),
        intent_classifier=RuleBasedLearningIntentClassifier(),
        context_loader=None,
        action_executor=None,
        guardrail=RuleBasedTutorGuardrail(),
        clock=lambda: NOW,
        language_service=language_service or UnavailableLanguageService(),
        language_service_enabled=language_service_enabled,
    )
    return GraphNodes(deps)


def _state(user_input: str, **overrides):
    state = new_state(
        thread_id=str(uuid4()), run_id=str(uuid4()), learner_id=str(uuid4()), correlation_id=str(uuid4()),
        graph_version="learning-coach-graph-v1", user_input=user_input, requested_context_type="GENERAL_EDUCATION",
    )
    state.update(overrides)
    return state


async def test_feature_flag_disabled_hebrew_question_behaves_like_pre_phase_baseline() -> None:
    language_service = FakeLanguageService()
    nodes = _nodes(language_service_enabled=False, language_service=language_service)
    state = _state(_HEBREW_QUESTION)

    result = await nodes.evaluate_input_guardrail(state)

    assert result['guardrail_result']['action'] == 'FALLBACK'
    assert result['guardrail_result']['safe_response_override'] == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK
    assert result['language_preparation']['intent_query'] == _HEBREW_QUESTION
    assert result['language_preparation']['translation_attempted'] is False
    assert language_service.translate_calls == []


class TestFeatureFlagDisabledIsByteIdenticalToBaseline:
    async def test_english_refusal_text_unchanged_with_flag_on_or_off(self) -> None:
        for enabled in (True, False):
            nodes = _nodes(language_service_enabled=enabled)
            state = _state("should I buy Apple stock right now?")
            guardrail_result = (await nodes.evaluate_input_guardrail(state))["guardrail_result"]
            state["guardrail_result"] = guardrail_result
            result = await nodes.build_refusal_response(state)
            assert result["final_response"]["answer_markdown"] == guardrail_result["safe_response_override"]

    async def test_english_fallback_text_unchanged_with_flag_on_or_off(self) -> None:
        results = []
        for enabled in (True, False):
            nodes = _nodes(language_service_enabled=enabled)
            state = _state("Can you recommend a good pizza restaurant near me?")
            result = await nodes.build_fallback_response(state)
            results.append(result["final_response"]["answer_markdown"])
        assert results[0] == results[1]

    async def test_disabled_flag_never_calls_language_service_detect(self) -> None:
        class ExplodingLanguageService(UnavailableLanguageService):
            def detect_language(self, text: str) -> DetectedLanguage:
                raise AssertionError("detect_language must not be called when the feature flag is disabled")

        nodes = _nodes(language_service_enabled=False, language_service=ExplodingLanguageService())
        state = _state(_HEBREW_QUESTION)
        # Must not raise.
        await nodes.evaluate_input_guardrail(state)
        await nodes.build_fallback_response(state)


class TestHebrewLocalization:
    async def test_evaluate_input_guardrail_allows_on_topic_hebrew_question(self) -> None:
        nodes = _nodes(language_service=FakeLanguageService())
        state = _state(_HEBREW_QUESTION)
        result = await nodes.evaluate_input_guardrail(state)
        assert result["guardrail_result"]["action"] == "ALLOW"

    async def test_build_refusal_response_uses_hebrew_text_for_hebrew_input(self) -> None:
        nodes = _nodes(language_service=FakeLanguageService())
        state = _state("האם כדאי לי לבצע buy NVDA עכשיו?")
        guardrail_result = (await nodes.evaluate_input_guardrail(state))["guardrail_result"]
        assert guardrail_result["action"] == "REFUSE"
        state["guardrail_result"] = guardrail_result
        result = await nodes.build_refusal_response(state)
        assert result["final_response"]["answer_markdown"] == EXACT_ADVICE_REFUSAL_HE

    async def test_build_refusal_response_falls_back_to_localized_default_when_no_override(self) -> None:
        nodes = _nodes()
        state = _state(_HEBREW_QUESTION)  # no guardrail_result set on state at all
        result = await nodes.build_refusal_response(state)
        assert result["final_response"]["answer_markdown"] == EXACT_ADVICE_REFUSAL_HE

    async def test_build_fallback_response_uses_hebrew_text_for_hebrew_input(self) -> None:
        nodes = _nodes()
        state = _state(_HEBREW_QUESTION)
        result = await nodes.build_fallback_response(state)
        message = result["final_response"]["answer_markdown"]
        assert message.startswith(EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE)
        assert result["selected_route"] == LearningOrchestratorRoute.FALLBACK.value

    async def test_build_fallback_response_uses_english_text_for_english_input(self) -> None:
        nodes = _nodes()
        state = _state("Can you recommend a good pizza restaurant near me?")
        result = await nodes.build_fallback_response(state)
        assert result["final_response"]["answer_markdown"].startswith(
            localize(LocalizedMessageKey.INSUFFICIENT_EVIDENCE, language=DetectedLanguage.EN)
        )


#: The three Hebrew Coach requests this phase must route correctly, with
#: the bounded English intent query a real provider would return for each.
_HEBREW_INTENT_CASES = (
    ("התחל תרגול", "start practice session", LearningIntent.START_DAILY_PRACTICE, LearningOrchestratorRoute.PRACTICE_ACTION),
    (
        "תעשה לי מבחן אבחון", "start a diagnostic assessment",
        LearningIntent.START_DIAGNOSTIC, LearningOrchestratorRoute.DIAGNOSTIC_ACTION,
    ),
    (
        "מה זה פיזור סיכונים?", "what is diversification",
        LearningIntent.EXPLAIN_CONCEPT, LearningOrchestratorRoute.GROUNDED_EXPLANATION,
    ),
)


class TestHebrewIntentRouting:
    """Phase G2E2A req. 3: the intent classifier's vocabulary is
    English-only, so handing it raw Hebrew produced `UNKNOWN` for every
    Hebrew request - which routed every one of them to the fallback.

    `evaluate_input_guardrail` now produces ONE bounded English query per
    run and `classify_intent` consumes that, so a Hebrew learner reaches
    the same route an equivalent English request would.
    """

    def _language_service(self) -> FakeLanguageService:
        return FakeLanguageService(
            translations={hebrew: english for hebrew, english, _intent, _route in _HEBREW_INTENT_CASES}
        )

    @pytest.mark.parametrize("hebrew,english,expected_intent,expected_route", _HEBREW_INTENT_CASES)
    async def test_hebrew_request_reaches_the_expected_intent_and_route(
        self, hebrew: str, english: str, expected_intent: LearningIntent,
        expected_route: LearningOrchestratorRoute,
    ) -> None:
        nodes = _nodes(language_service=self._language_service())
        state = _state(hebrew)

        state.update(await nodes.evaluate_input_guardrail(state))
        state.update(await nodes.classify_intent(state))
        state.update(await nodes.select_route(state))

        assert state["intent_classification"]["intent"] == expected_intent.value
        assert state["selected_route"] == expected_route.value

    @pytest.mark.parametrize("hebrew,english,expected_intent,expected_route", _HEBREW_INTENT_CASES)
    async def test_the_original_hebrew_input_is_preserved_exactly(
        self, hebrew: str, english: str, expected_intent: LearningIntent,
        expected_route: LearningOrchestratorRoute,
    ) -> None:
        """The bounded English query drives routing only - the learner's
        own words must never be overwritten in state."""
        nodes = _nodes(language_service=self._language_service())
        state = _state(hebrew)

        state.update(await nodes.evaluate_input_guardrail(state))
        state.update(await nodes.classify_intent(state))

        assert state["user_input"] == hebrew

    async def test_the_bounded_english_query_is_recorded_in_state(self) -> None:
        language_service = self._language_service()
        nodes = _nodes(language_service=language_service)
        state = _state("מה זה פיזור סיכונים?")

        result = await nodes.evaluate_input_guardrail(state)

        preparation = result["language_preparation"]
        assert preparation["detected_language"] == DetectedLanguage.HE.value
        assert preparation["intent_query"] == "what is diversification"
        assert preparation["translation_attempted"] is True
        assert preparation["translation_failed"] is False

    async def test_classify_intent_never_triggers_a_second_translation(self) -> None:
        language_service = self._language_service()
        nodes = _nodes(language_service=language_service)
        state = _state("מה זה פיזור סיכונים?")

        state.update(await nodes.evaluate_input_guardrail(state))
        await nodes.classify_intent(state)

        assert language_service.translate_calls == ["מה זה פיזור סיכונים?"]

    async def test_the_classifier_receives_the_english_query_not_the_hebrew_text(self) -> None:
        recorded: list[str] = []

        class RecordingClassifier(RuleBasedLearningIntentClassifier):
            async def classify(self, *, learner_id, user_input, context_type, context_references):
                recorded.append(user_input)
                return await super().classify(
                    learner_id=learner_id, user_input=user_input, context_type=context_type,
                    context_references=context_references,
                )

        deps = NodeDependencies(
            unit_of_work_factory=_uow_factory(), intent_classifier=RecordingClassifier(),
            context_loader=None, action_executor=None, guardrail=RuleBasedTutorGuardrail(), clock=lambda: NOW,
            language_service=self._language_service(), language_service_enabled=True,
        )
        nodes = GraphNodes(deps)
        state = _state("התחל תרגול")

        state.update(await nodes.evaluate_input_guardrail(state))
        await nodes.classify_intent(state)

        assert recorded == ["start practice session"]

    async def test_english_requests_still_reach_the_classifier_byte_identically(self) -> None:
        recorded: list[str] = []

        class RecordingClassifier(RuleBasedLearningIntentClassifier):
            async def classify(self, *, learner_id, user_input, context_type, context_references):
                recorded.append(user_input)
                return await super().classify(
                    learner_id=learner_id, user_input=user_input, context_type=context_type,
                    context_references=context_references,
                )

        deps = NodeDependencies(
            unit_of_work_factory=_uow_factory(), intent_classifier=RecordingClassifier(),
            context_loader=None, action_executor=None, guardrail=RuleBasedTutorGuardrail(), clock=lambda: NOW,
            language_service=self._language_service(), language_service_enabled=True,
        )
        nodes = GraphNodes(deps)
        state = _state("start my daily practice")

        state.update(await nodes.evaluate_input_guardrail(state))
        await nodes.classify_intent(state)

        assert recorded == ["start my daily practice"]


class TestTranslationFailureFailsClosed:
    """Phase G2E2A req. 3/6: a failed translation must never silently
    continue into intent classification, unrelated retrieval, or model
    generation - it produces the exact localized bounded fallback."""

    async def test_failed_translation_yields_the_localized_fallback_decision(self) -> None:
        nodes = _nodes(language_service=FakeLanguageService(raise_error=True))
        state = _state(_HEBREW_QUESTION)

        result = await nodes.evaluate_input_guardrail(state)

        guardrail_result = result["guardrail_result"]
        assert guardrail_result["action"] == "FALLBACK"
        assert guardrail_result["matched_rule_codes"] == ["LANGUAGE_TRANSLATION_UNAVAILABLE"]
        assert guardrail_result["safe_response_override"] == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE
        assert result["language_preparation"]["translation_failed"] is True

    async def test_the_run_routes_to_the_hebrew_fallback_response(self) -> None:
        nodes = _nodes(language_service=FakeLanguageService(raise_error=True))
        state = _state(_HEBREW_QUESTION)

        state.update(await nodes.evaluate_input_guardrail(state))
        result = await nodes.build_fallback_response(state)

        assert result["selected_route"] == LearningOrchestratorRoute.FALLBACK.value
        assert result["final_response"]["answer_markdown"].startswith(EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE)
        assert result["final_response"]["citations"] == []

    async def test_an_unsafe_hebrew_request_is_refused_without_being_translated(self) -> None:
        """Translation failure must never let an otherwise-unsafe request
        through - and an already-refused request is never sent to the
        translation provider in the first place."""
        language_service = FakeLanguageService(raise_error=True)
        nodes = _nodes(language_service=language_service)
        state = _state("איזו מניה כדאי לי לקנות?")

        result = await nodes.evaluate_input_guardrail(state)

        assert result["guardrail_result"]["action"] == "REFUSE"
        assert result["guardrail_result"]["safe_response_override"] == EXACT_ADVICE_REFUSAL_HE
        assert language_service.translate_calls == []


class TestTranslatedGuardrailDefenseInDepth:
    async def test_unsafe_translation_escalates_an_otherwise_allowed_hebrew_request(self) -> None:
        language_service = FakeLanguageService(default_query="should I buy NVDA now")
        nodes = _nodes(language_service=language_service)
        state = _state("מה המצב עם המניה הזאת?")

        result = await nodes.evaluate_input_guardrail(state)

        assert result["guardrail_result"]["action"] == "REFUSE"
        assert result["guardrail_result"]["safe_response_override"] == EXACT_ADVICE_REFUSAL_HE

    async def test_a_benign_translation_never_downgrades_an_allowed_request(self) -> None:
        nodes = _nodes(language_service=FakeLanguageService())
        state = _state(_HEBREW_QUESTION)

        result = await nodes.evaluate_input_guardrail(state)

        assert result["guardrail_result"]["action"] == "ALLOW"


class TestPreparedLanguageIsHandedToTutorRoutes:
    """Phase G2E2A req. 3: every subgraph route that reaches a tutor
    service passes this run's existing preparation through, so no route
    causes a second translation of the same text."""

    async def test_prepared_language_is_rebuilt_from_state(self) -> None:
        nodes = _nodes(language_service=FakeLanguageService())
        state = _state(_HEBREW_QUESTION)
        state.update(await nodes.evaluate_input_guardrail(state))

        prepared = prepared_language_from_state(state)

        assert prepared is not None
        assert prepared.original_text == _HEBREW_QUESTION
        assert prepared.detected_language == DetectedLanguage.HE
        assert prepared.search_query == "diversification portfolio risk"
        assert prepared.translation_succeeded is True

    async def test_a_state_without_a_preparation_yields_none(self) -> None:
        """A directly-invoked subgraph (or a checkpoint written before this
        phase) must not crash - the tutor service simply prepares its own."""
        assert prepared_language_from_state(_state(_HEBREW_QUESTION)) is None

    async def test_an_english_run_carries_the_original_text_as_its_query(self) -> None:
        nodes = _nodes(language_service=FakeLanguageService())
        state = _state("What is diversification?")
        state.update(await nodes.evaluate_input_guardrail(state))

        prepared = prepared_language_from_state(state)

        assert prepared is not None
        assert prepared.detected_language == DetectedLanguage.EN
        assert prepared.search_query == "What is diversification?"
        assert prepared.translation_attempted is False
