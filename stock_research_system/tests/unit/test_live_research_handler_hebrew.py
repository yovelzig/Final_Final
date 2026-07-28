"""Unit tests for `LiveResearchRunExecutionJobHandler`'s Phase G2E2A
Hebrew query-translation bridge.

Reuses the fakes already defined in `test_live_research_run_execution_handler.py`
(`FakeDiscoveryProvider`, `FakeResearchRequestService`, `_params`, `_context`,
`_fetch_result`) rather than duplicating them.
"""

from __future__ import annotations

import pytest

from stock_research_core.application.exceptions import LanguageServiceError
from stock_research_core.application.language.detection import detect_language as real_detect_language
from stock_research_core.application.language.enums import DetectedLanguage
from stock_research_core.application.language.models import TranslationResult
from stock_research_core.application.operations.handlers import LiveResearchRunExecutionJobHandler
from stock_research_core.domain.live_research.enums import ResearchScope

from tests.unit.test_live_research_run_execution_handler import (
    FakeDiscoveryProvider,
    FakeResearchRequestService,
    _candidate,
    _context,
    _fetch_result,
    _params,
)

_HEBREW_QUESTION = "מה קורה עם החברה Acme לאחרונה?"


class FakeLanguageService:
    def __init__(self, *, translated_query: str | None = None, raise_error: bool = False) -> None:
        self.translated_query = translated_query
        self.raise_error = raise_error
        self.translate_calls: list[str] = []

    def detect_language(self, text: str) -> DetectedLanguage:
        return real_detect_language(text)

    def localize(self, key, *, language):  # pragma: no cover - not exercised by this handler
        raise NotImplementedError

    async def translate_to_english_query(self, text: str, *, source_language: DetectedLanguage) -> TranslationResult:
        self.translate_calls.append(text)
        if self.raise_error:
            raise LanguageServiceError("translation unavailable (test)")
        return TranslationResult(
            translated_query=self.translated_query or "Acme Corp recent news",
            source_language=source_language, translation_policy_version="test-v1",
        )


def _handler(*, discovery=None, service=None, language_service=None, language_service_enabled=True):
    service = service if service is not None else FakeResearchRequestService()
    handler = LiveResearchRunExecutionJobHandler(
        research_request_service=service, discovery_search_provider=discovery,
        official_company_data_provider=None, jobs_enabled=True, discovery_max_results=10,
        language_service=language_service, language_service_enabled=language_service_enabled,
    )
    return handler, service


class _NoopProgress:
    async def report(self, *, current, total=None, message=None):
        pass


@pytest.mark.asyncio
class TestHebrewQueryTranslation:
    async def test_hebrew_original_question_is_translated_for_the_search_provider(self) -> None:
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search"))
        language_service = FakeLanguageService(translated_query="Acme Corp recent news")
        handler, service = _handler(discovery=discovery, language_service=language_service)

        await handler.handle(
            context=_context(),
            parameters=_params(ResearchScope.NEWS_SCAN, original_question=_HEBREW_QUESTION),
            progress=_NoopProgress(),
        )

        assert language_service.translate_calls == [_HEBREW_QUESTION]
        assert discovery.calls[0].query == "Acme Corp recent news"

    async def test_original_question_is_preserved_verbatim_in_submit_request(self) -> None:
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search"))
        language_service = FakeLanguageService(translated_query="Acme Corp recent news")
        handler, service = _handler(discovery=discovery, language_service=language_service)

        await handler.handle(
            context=_context(),
            parameters=_params(ResearchScope.NEWS_SCAN, original_question=_HEBREW_QUESTION),
            progress=_NoopProgress(),
        )

        assert service.submit_calls[0]["original_question"] == _HEBREW_QUESTION

    async def test_english_question_is_never_translated(self) -> None:
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search"))
        language_service = FakeLanguageService()
        handler, _service = _handler(discovery=discovery, language_service=language_service)

        await handler.handle(
            context=_context(),
            parameters=_params(ResearchScope.NEWS_SCAN, original_question="What about Acme?"),
            progress=_NoopProgress(),
        )

        assert language_service.translate_calls == []
        assert discovery.calls[0].query == "What about Acme?"

    async def test_translation_failure_falls_back_to_original_question_never_fails_the_job(self) -> None:
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search", candidates=[_candidate()]))
        language_service = FakeLanguageService(raise_error=True)
        handler, service = _handler(discovery=discovery, language_service=language_service)

        await handler.handle(
            context=_context(),
            parameters=_params(ResearchScope.NEWS_SCAN, original_question=_HEBREW_QUESTION),
            progress=_NoopProgress(),
        )

        assert language_service.translate_calls == [_HEBREW_QUESTION]
        assert discovery.calls[0].query == _HEBREW_QUESTION
        # Translation failure degrades the *query* only - it never raises
        # out of `handle()`, and the run completes normally.
        assert service.complete_run_calls
        assert service.fail_run_calls == []

    async def test_feature_flag_disabled_never_calls_translate(self) -> None:
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search"))
        language_service = FakeLanguageService(translated_query="Acme Corp recent news")
        handler, _service = _handler(discovery=discovery, language_service=language_service, language_service_enabled=False)

        await handler.handle(
            context=_context(),
            parameters=_params(ResearchScope.NEWS_SCAN, original_question=_HEBREW_QUESTION),
            progress=_NoopProgress(),
        )

        assert language_service.translate_calls == []
        assert discovery.calls[0].query == _HEBREW_QUESTION

    async def test_default_construction_without_language_service_behaves_like_before_phase(self) -> None:
        """No `language_service` passed at all (the default) - matches
        every pre-existing call site of this handler."""
        discovery = FakeDiscoveryProvider(result=_fetch_result("perplexity_search"))
        handler, _service = _handler(discovery=discovery, language_service=None, language_service_enabled=True)

        await handler.handle(
            context=_context(),
            parameters=_params(ResearchScope.NEWS_SCAN, original_question=_HEBREW_QUESTION),
            progress=_NoopProgress(),
        )

        # `UnavailableLanguageService` default: translation always raises,
        # so the discovery query is still the original question.
        assert discovery.calls[0].query == _HEBREW_QUESTION
