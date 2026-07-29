"""Unit tests for `application.language.service.LanguageBridgeService`
and `infrastructure.language.model_translation_adapter.ModelTranslationAdapter` -
in-memory fakes only, no real model provider."""

from __future__ import annotations

from uuid import uuid4

import pytest

from stock_research_core.application.ai_tutor.models import TutorModelResult
from stock_research_core.application.language.detection import Language
from stock_research_core.application.language.service import LanguageBridgeService
from stock_research_core.domain.ai_tutor.enums import TutorProviderType
from stock_research_core.infrastructure.language.model_translation_adapter import ModelTranslationAdapter

_HEBREW_QUESTION = "מה קרה למניית NVDA השבוע?"
_ENGLISH_QUESTION = "What happened to NVDA this week?"


class _FakeTranslator:
    def __init__(self, *, translated: str | None = None, error: Exception | None = None) -> None:
        self.translated = translated or _ENGLISH_QUESTION
        self.error = error
        self.calls: list[str] = []

    async def translate_to_english(self, *, text: str) -> str:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return self.translated


class _FakeTutorModel:
    def __init__(self, *, answer_markdown: str) -> None:
        self.answer_markdown = answer_markdown
        self.requests: list = []

    async def generate(self, request):
        self.requests.append(request)
        return TutorModelResult(
            answer_markdown=self.answer_markdown, cited_chunk_ids=[], provider_type=TutorProviderType.EXTRACTIVE,
            model_name="fake-translation-model",
        )


async def test_disabled_bridge_never_translates() -> None:
    translator = _FakeTranslator()
    bridge = LanguageBridgeService(translator=translator, enabled=False)
    result = await bridge.prepare_retrieval_query(_HEBREW_QUESTION)
    assert result.retrieval_query == _HEBREW_QUESTION
    assert result.translated is False
    assert result.detected_language == Language.HEBREW
    assert translator.calls == []


async def test_english_question_is_never_translated_even_when_enabled() -> None:
    translator = _FakeTranslator()
    bridge = LanguageBridgeService(translator=translator, enabled=True)
    result = await bridge.prepare_retrieval_query(_ENGLISH_QUESTION)
    assert result.retrieval_query == _ENGLISH_QUESTION
    assert result.translated is False
    assert result.detected_language == Language.ENGLISH
    assert translator.calls == []


async def test_hebrew_question_translated_when_enabled() -> None:
    translator = _FakeTranslator(translated=_ENGLISH_QUESTION)
    bridge = LanguageBridgeService(translator=translator, enabled=True)
    result = await bridge.prepare_retrieval_query(_HEBREW_QUESTION)
    assert result.retrieval_query == _ENGLISH_QUESTION
    assert result.translated is True
    assert result.detected_language == Language.HEBREW
    # The bridge only ever sends the original question, unchanged, to the translator.
    assert translator.calls == [_HEBREW_QUESTION]


async def test_translation_failure_falls_back_to_original_question_without_crashing() -> None:
    translator = _FakeTranslator(error=RuntimeError("provider unavailable"))
    bridge = LanguageBridgeService(translator=translator, enabled=True)
    result = await bridge.prepare_retrieval_query(_HEBREW_QUESTION)
    assert result.retrieval_query == _HEBREW_QUESTION
    assert result.translated is False


async def test_blank_translation_result_falls_back_to_original_question() -> None:
    translator = _FakeTranslator(translated="   ")
    bridge = LanguageBridgeService(translator=translator, enabled=True)
    result = await bridge.prepare_retrieval_query(_HEBREW_QUESTION)
    assert result.retrieval_query == _HEBREW_QUESTION
    assert result.translated is False


async def test_no_translator_configured_falls_back_safely() -> None:
    bridge = LanguageBridgeService(translator=None, enabled=True)
    result = await bridge.prepare_retrieval_query(_HEBREW_QUESTION)
    assert result.retrieval_query == _HEBREW_QUESTION
    assert result.translated is False


async def test_model_translation_adapter_sends_no_retrieved_candidates() -> None:
    tutor_model = _FakeTutorModel(answer_markdown=_ENGLISH_QUESTION)
    adapter = ModelTranslationAdapter(tutor_model=tutor_model)
    translated = await adapter.translate_to_english(text=_HEBREW_QUESTION)
    assert translated == _ENGLISH_QUESTION
    assert tutor_model.requests[0].retrieved_candidates == []
    assert tutor_model.requests[0].user_question == _HEBREW_QUESTION


async def test_model_translation_adapter_bounds_input_length() -> None:
    tutor_model = _FakeTutorModel(answer_markdown="x")
    adapter = ModelTranslationAdapter(tutor_model=tutor_model)
    long_text = "א" * 5000
    await adapter.translate_to_english(text=long_text)
    assert len(tutor_model.requests[0].user_question) == 2000
