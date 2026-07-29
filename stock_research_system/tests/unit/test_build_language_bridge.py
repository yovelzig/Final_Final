"""Unit tests for `infrastructure.language.model_translation_adapter.
build_language_bridge` (spec G2D2 section 6/11) - the one place
`HEBREW_QUERY_BRIDGE_ENABLED` is turned into a real `LanguageBridgeService`,
shared by every composition root."""

from __future__ import annotations

from stock_research_core.application.ai_tutor.models import TutorModelRequest, TutorModelResult
from stock_research_core.domain.ai_tutor.enums import TutorProviderType
from stock_research_core.infrastructure.language.model_translation_adapter import (
    ModelTranslationAdapter,
    build_language_bridge,
)


class _FakeTutorModel:
    provider_type = TutorProviderType.EXTRACTIVE

    def __init__(self, translation: str) -> None:
        self._translation = translation
        self.calls: list[TutorModelRequest] = []

    async def generate(self, request: TutorModelRequest) -> TutorModelResult:
        self.calls.append(request)
        return TutorModelResult(
            answer_markdown=self._translation, cited_chunk_ids=[], provider_type=self.provider_type,
            model_name="fake",
        )


class TestBuildLanguageBridgeDisabled:
    async def test_disabled_bridge_never_translates(self) -> None:
        tutor_model = _FakeTutorModel("should never be used")
        bridge = build_language_bridge(enabled=False, tutor_model=tutor_model)

        result = await bridge.prepare_retrieval_query("מה זה ריבית דריבית?")

        assert result.translated is False
        assert result.retrieval_query == "מה זה ריבית דריבית?"
        assert tutor_model.calls == []


class TestBuildLanguageBridgeEnabled:
    async def test_enabled_bridge_translates_hebrew_questions(self) -> None:
        tutor_model = _FakeTutorModel("What is compound interest?")
        bridge = build_language_bridge(enabled=True, tutor_model=tutor_model)

        result = await bridge.prepare_retrieval_query("מה זה ריבית דריבית?")

        assert result.translated is True
        assert result.retrieval_query == "What is compound interest?"
        assert len(tutor_model.calls) == 1

    async def test_enabled_bridge_leaves_english_questions_untouched(self) -> None:
        tutor_model = _FakeTutorModel("should never be used")
        bridge = build_language_bridge(enabled=True, tutor_model=tutor_model)

        result = await bridge.prepare_retrieval_query("What is compound interest?")

        assert result.translated is False
        assert result.retrieval_query == "What is compound interest?"
        assert tutor_model.calls == []

    async def test_enabled_bridge_uses_a_model_translation_adapter(self) -> None:
        tutor_model = _FakeTutorModel("translated")
        bridge = build_language_bridge(enabled=True, tutor_model=tutor_model)

        assert isinstance(bridge._translator, ModelTranslationAdapter)  # noqa: SLF001 - test-only introspection
