"""Unit tests for `infrastructure.language.composition.build_language_service`/
`close_language_service` (Phase G2E2A correction pass).

This is the ONE shared composition function every process (API,
Celery worker, and per-G2D2 the Coach research-resume path) must call -
see `test_worker_language_composition.py` for proof the Celery worker
composition root actually calls it and gets the same kind of object a
directly-constructed test would. Pure composition-root tests: no FastAPI
app constructed, no database/Redis touched, no real network call ever
made.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from stock_research_core.application.exceptions import LanguageServiceConfigurationError
from stock_research_core.application.language.unavailable_language_service import UnavailableLanguageService
from stock_research_core.infrastructure.ai_tutor.config import TutorModelSettings
from stock_research_core.infrastructure.language.composition import build_language_service, close_language_service
from stock_research_core.infrastructure.language.config import LanguageServiceSettings
from stock_research_core.infrastructure.language.llm_backed_language_service import LlmBackedLanguageService


def _language_settings(**overrides) -> LanguageServiceSettings:
    return LanguageServiceSettings(_env_file=None, **overrides)


def _tutor_settings(**overrides) -> TutorModelSettings:
    return TutorModelSettings(_env_file=None, **overrides)


class TestDisabledByDefault:
    def test_default_settings_build_unavailable_service(self) -> None:
        service = build_language_service(_language_settings())
        assert isinstance(service, UnavailableLanguageService)

    def test_explicitly_disabled_builds_unavailable_service_even_if_llm_backed_requested(self) -> None:
        service = build_language_service(
            _language_settings(hebrew_query_bridge_enabled=False, language_service_provider="llm_backed")
        )
        assert isinstance(service, UnavailableLanguageService)

    def test_enabled_unavailable_provider_builds_unavailable_service(self) -> None:
        service = build_language_service(
            _language_settings(hebrew_query_bridge_enabled=True, language_service_provider="unavailable")
        )
        assert isinstance(service, UnavailableLanguageService)


class TestExplicitCredentials:
    def test_enabled_llm_backed_with_own_credentials_builds_adapter(self) -> None:
        settings = _language_settings(
            hebrew_query_bridge_enabled=True, language_service_provider="llm_backed",
            language_service_base_url="https://example.internal/v1", language_service_api_key="key",
            language_service_model_name="test-model", language_service_timeout_seconds=12.0,
        )
        service = build_language_service(settings)
        try:
            assert isinstance(service, LlmBackedLanguageService)
            assert service._wire_shape == "openai_compatible"  # noqa: SLF001 - test-only introspection
        finally:
            asyncio.run(service.aclose())


class TestTutorProviderReuse:
    """Section 2: avoid requiring a second copy of an API key when the
    existing server-side Tutor provider configuration can safely be
    reused."""

    def test_reuses_openai_compatible_tutor_credentials_when_own_are_blank(self) -> None:
        settings = _language_settings(hebrew_query_bridge_enabled=True, language_service_provider="llm_backed")
        tutor_settings = _tutor_settings(
            tutor_model_provider="openai_compatible", tutor_model_base_url="http://localhost:11434/v1",
            tutor_model_api_key="tutor-key", tutor_model_name="llama3",
        )
        service = build_language_service(settings, tutor_model_settings=tutor_settings)
        try:
            assert isinstance(service, LlmBackedLanguageService)
            assert service._wire_shape == "openai_compatible"  # noqa: SLF001
            assert service._base_url == "http://localhost:11434/v1"  # noqa: SLF001
            assert service._api_key == "tutor-key"  # noqa: SLF001
            assert service._model_name == "llama3"  # noqa: SLF001
        finally:
            asyncio.run(service.aclose())

    def test_reuses_ollama_cloud_tutor_credentials_and_selects_native_wire_shape(self) -> None:
        settings = _language_settings(hebrew_query_bridge_enabled=True, language_service_provider="llm_backed")
        tutor_settings = _tutor_settings(
            tutor_model_provider="ollama_cloud", tutor_model_base_url="https://ollama.com/api",
            tutor_model_api_key="ollama-key", tutor_model_name="gpt-oss:20b",
        )
        service = build_language_service(settings, tutor_model_settings=tutor_settings)
        try:
            assert isinstance(service, LlmBackedLanguageService)
            assert service._wire_shape == "ollama_cloud"  # noqa: SLF001
            assert service._api_key == "ollama-key"  # noqa: SLF001
        finally:
            asyncio.run(service.aclose())

    def test_own_explicit_credentials_take_priority_over_reuse(self) -> None:
        settings = _language_settings(
            hebrew_query_bridge_enabled=True, language_service_provider="llm_backed",
            language_service_base_url="https://dedicated-translator.internal/v1",
            language_service_api_key="dedicated-key", language_service_model_name="dedicated-model",
        )
        tutor_settings = _tutor_settings(
            tutor_model_provider="openai_compatible", tutor_model_base_url="http://localhost:11434/v1",
            tutor_model_api_key="tutor-key", tutor_model_name="llama3",
        )
        service = build_language_service(settings, tutor_model_settings=tutor_settings)
        try:
            assert service._base_url == "https://dedicated-translator.internal/v1"  # noqa: SLF001
            assert service._api_key == "dedicated-key"  # noqa: SLF001
        finally:
            asyncio.run(service.aclose())

    def test_extractive_tutor_provider_cannot_be_reused(self) -> None:
        settings = _language_settings(hebrew_query_bridge_enabled=True, language_service_provider="llm_backed")
        tutor_settings = _tutor_settings(tutor_model_provider="extractive")
        with pytest.raises(LanguageServiceConfigurationError):
            build_language_service(settings, tutor_model_settings=tutor_settings)

    def test_no_tutor_settings_and_no_own_credentials_raises_configuration_error(self) -> None:
        settings = _language_settings(hebrew_query_bridge_enabled=True, language_service_provider="llm_backed")
        with pytest.raises(LanguageServiceConfigurationError):
            build_language_service(settings, tutor_model_settings=None)

    def test_configuration_error_never_makes_a_network_call(self) -> None:
        # If this raised anything other than LanguageServiceConfigurationError
        # (e.g. a network-related exception), composition would not be
        # "network-free at startup" as required.
        settings = _language_settings(hebrew_query_bridge_enabled=True, language_service_provider="llm_backed")
        tutor_settings = _tutor_settings(tutor_model_provider="extractive")
        with pytest.raises(LanguageServiceConfigurationError) as exc_info:
            build_language_service(settings, tutor_model_settings=tutor_settings)
        # Never logs/exposes any API key in the error message.
        assert "key" not in str(exc_info.value).lower() or "api key" in str(exc_info.value).lower()


class TestLanguageServiceLifespanClose:
    async def test_closes_an_owned_llm_backed_client(self) -> None:
        service = LlmBackedLanguageService(
            base_url="https://example.internal/v1", api_key="key", model_name="test-model",
        )
        owned_client = service._client  # noqa: SLF001 - test-only introspection

        await close_language_service(service)

        assert owned_client.is_closed

    async def test_does_not_close_an_injected_llm_backed_client(self) -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
        service = LlmBackedLanguageService(
            base_url="https://example.internal/v1", api_key="key", model_name="test-model", client=client,
        )

        await close_language_service(service)

        assert not client.is_closed
        await client.aclose()

    async def test_unavailable_service_has_nothing_to_close(self) -> None:
        await close_language_service(UnavailableLanguageService())
