"""Unit tests for `application.ai_tutor.model_router` (spec G2D2 section
5.A-F): deterministic provider selection, never an LLM-made choice."""

from __future__ import annotations

from stock_research_core.application.ai_tutor.model_router import TutorModelRouter, is_complex_question
from stock_research_core.application.ai_tutor.models import TutorModelRequest, TutorModelResult
from stock_research_core.application.exceptions import TutorModelProviderError
from stock_research_core.domain.ai_tutor.enums import TutorProviderType


def _request(question: str = "What is compound interest?") -> TutorModelRequest:
    return TutorModelRequest(
        system_instructions="You are a tutor.", user_question=question, conversation_messages=[],
        retrieved_candidates=[], prompt_version="v1",
    )


def _result(provider_type: TutorProviderType) -> TutorModelResult:
    return TutorModelResult(answer_markdown="ok", cited_chunk_ids=[], provider_type=provider_type, model_name="m")


class _FakeModel:
    provider_type: TutorProviderType
    _model_name = "fake-model"

    def __init__(self, provider_type: TutorProviderType, *, fail: bool = False) -> None:
        self.provider_type = provider_type
        self._fail = fail
        self.calls = 0

    async def generate(self, request: TutorModelRequest) -> TutorModelResult:
        self.calls += 1
        if self._fail:
            raise TutorModelProviderError("simulated provider failure")
        return _result(self.provider_type)


class TestIsComplexQuestion:
    def test_comparison_phrasing_is_complex(self) -> None:
        assert is_complex_question("Compare index funds versus individual stocks.")

    def test_ordinary_definitional_question_is_not_complex(self) -> None:
        assert not is_complex_question("What is compound interest?")

    def test_multi_metric_portfolio_question_is_complex(self) -> None:
        assert is_complex_question("How does my Sharpe ratio relate to my drawdown this quarter?")

    def test_synthesis_across_sources_is_complex(self) -> None:
        assert is_complex_question("Can you synthesize several reports about this sector?")


class TestCaseB_OrdinaryQuestionUsesOllamaPrimary:
    async def test_ordinary_question_calls_only_primary(self) -> None:
        primary = _FakeModel(TutorProviderType.OLLAMA_CLOUD)
        secondary = _FakeModel(TutorProviderType.OPENAI_REASONING)
        router = TutorModelRouter(primary=primary, secondary=secondary, secondary_enabled=True)

        result = await router.generate(_request("What is compound interest?"))

        assert result.provider_type == TutorProviderType.OLLAMA_CLOUD
        assert primary.calls == 1
        assert secondary.calls == 0


class TestCaseC_ComplexQuestionWithOpenAIEnabledUsesOpenAIPrimary:
    async def test_complex_question_routes_to_openai_first(self) -> None:
        primary = _FakeModel(TutorProviderType.OLLAMA_CLOUD)
        secondary = _FakeModel(TutorProviderType.OPENAI_REASONING)
        router = TutorModelRouter(primary=primary, secondary=secondary, secondary_enabled=True)

        result = await router.generate(_request("Compare index funds versus individual stocks."))

        assert result.provider_type == TutorProviderType.OPENAI_REASONING
        assert secondary.calls == 1
        assert primary.calls == 0

    async def test_complex_question_with_openai_disabled_uses_ollama(self) -> None:
        primary = _FakeModel(TutorProviderType.OLLAMA_CLOUD)
        secondary = _FakeModel(TutorProviderType.OPENAI_REASONING)
        router = TutorModelRouter(primary=primary, secondary=secondary, secondary_enabled=False)

        result = await router.generate(_request("Compare index funds versus individual stocks."))

        assert result.provider_type == TutorProviderType.OLLAMA_CLOUD
        assert primary.calls == 1
        assert secondary.calls == 0


class TestCaseD_OllamaFailureFallsBackToOpenAI:
    async def test_ordinary_question_ollama_failure_falls_back_to_openai(self) -> None:
        primary = _FakeModel(TutorProviderType.OLLAMA_CLOUD, fail=True)
        secondary = _FakeModel(TutorProviderType.OPENAI_REASONING)
        router = TutorModelRouter(primary=primary, secondary=secondary, secondary_enabled=True)

        result = await router.generate(_request("What is compound interest?"))

        assert result.provider_type == TutorProviderType.OPENAI_REASONING
        assert primary.calls == 1
        assert secondary.calls == 1

    async def test_ordinary_question_ollama_failure_with_openai_disabled_raises(self) -> None:
        primary = _FakeModel(TutorProviderType.OLLAMA_CLOUD, fail=True)
        router = TutorModelRouter(primary=primary, secondary=None, secondary_enabled=False)

        try:
            await router.generate(_request("What is compound interest?"))
            raised = False
        except TutorModelProviderError:
            raised = True
        assert raised
        assert primary.calls == 1


class TestCaseE_OpenAIFailureOnComplexQuestionFallsBackToOllama:
    async def test_complex_question_openai_failure_falls_back_to_ollama(self) -> None:
        primary = _FakeModel(TutorProviderType.OLLAMA_CLOUD)
        secondary = _FakeModel(TutorProviderType.OPENAI_REASONING, fail=True)
        router = TutorModelRouter(primary=primary, secondary=secondary, secondary_enabled=True)

        result = await router.generate(_request("Compare index funds versus individual stocks."))

        assert result.provider_type == TutorProviderType.OLLAMA_CLOUD
        assert secondary.calls == 1
        assert primary.calls == 1

    async def test_a_learner_is_never_left_ungrounded_when_both_fail(self) -> None:
        primary = _FakeModel(TutorProviderType.OLLAMA_CLOUD, fail=True)
        secondary = _FakeModel(TutorProviderType.OPENAI_REASONING, fail=True)
        router = TutorModelRouter(primary=primary, secondary=secondary, secondary_enabled=True)

        try:
            await router.generate(_request("Compare index funds versus individual stocks."))
            raised = False
        except TutorModelProviderError:
            raised = True
        assert raised


class TestProviderTypeReflectsPrimary:
    def test_router_provider_type_is_the_primary_provider(self) -> None:
        primary = _FakeModel(TutorProviderType.OLLAMA_CLOUD)
        router = TutorModelRouter(primary=primary)
        assert router.provider_type == TutorProviderType.OLLAMA_CLOUD

    def test_secondary_none_never_enables_routing(self) -> None:
        primary = _FakeModel(TutorProviderType.OLLAMA_CLOUD)
        router = TutorModelRouter(primary=primary, secondary=None, secondary_enabled=True)
        assert router._secondary_enabled is False  # noqa: SLF001 - test-only introspection
