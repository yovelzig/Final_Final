"""Unit tests for `app_factory._build_tutor_model` (Phase D provider dispatch).

Pure composition-root tests: no FastAPI app is constructed, no database or
Redis is touched, and no real network call is ever made (the OpenAI-compatible
and Ollama Cloud adapters only open an `httpx.AsyncClient`, which is closed
immediately after each assertion).
"""

from __future__ import annotations

import httpx
import pytest

from stock_research_core.api.app_factory import (
    _build_knowledge_sufficiency_gate,
    _build_tutor_model,
    _close_tutor_model,
)
from stock_research_core.application.ai_tutor.sufficiency import (
    DisabledKnowledgeSufficiencyGate,
    RuleBasedKnowledgeSufficiencyGate,
)
from stock_research_core.infrastructure.ai_tutor.config import KnowledgeSufficiencySettings, TutorModelSettings
from stock_research_core.infrastructure.ai_tutor.extractive_tutor import DeterministicExtractiveTutor
from stock_research_core.infrastructure.ai_tutor.ollama_cloud_tutor import OllamaCloudTutorAdapter
from stock_research_core.infrastructure.ai_tutor.openai_compatible_tutor import OpenAICompatibleTutorAdapter

_TUTOR_ENV_VARS = (
    "TUTOR_MODEL_PROVIDER",
    "TUTOR_MODEL_BASE_URL",
    "TUTOR_MODEL_API_KEY",
    "TUTOR_MODEL_NAME",
    "TUTOR_MODEL_TIMEOUT_SECONDS",
    "TUTOR_MODEL_THINKING_LEVEL",
)


@pytest.fixture(autouse=True)
def _clear_ambient_tutor_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _TUTOR_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _settings(**overrides) -> TutorModelSettings:
    return TutorModelSettings(_env_file=None, **overrides)


class TestProviderDispatch:
    def test_default_settings_build_extractive(self) -> None:
        provider = _build_tutor_model(_settings())
        assert isinstance(provider, DeterministicExtractiveTutor)

    def test_extractive_provider_name_builds_extractive(self) -> None:
        provider = _build_tutor_model(_settings(tutor_model_provider="extractive"))
        assert isinstance(provider, DeterministicExtractiveTutor)

    def test_openai_compatible_builds_openai_compatible_adapter(self) -> None:
        provider = _build_tutor_model(
            _settings(
                tutor_model_provider="openai_compatible",
                tutor_model_base_url="http://localhost:11434/v1",
                tutor_model_name="llama3",
            )
        )
        try:
            assert isinstance(provider, OpenAICompatibleTutorAdapter)
            assert not isinstance(provider, OllamaCloudTutorAdapter)
        finally:
            import asyncio

            asyncio.run(provider.aclose())

    def test_ollama_cloud_builds_ollama_cloud_adapter(self) -> None:
        provider = _build_tutor_model(
            _settings(
                tutor_model_provider="ollama_cloud",
                tutor_model_base_url="https://ollama.com/api",
                tutor_model_api_key="test-only-key",
                tutor_model_name="gpt-oss:20b",
                tutor_model_thinking_level="low",
            )
        )
        try:
            assert isinstance(provider, OllamaCloudTutorAdapter)
            assert provider._thinking_level == "low"  # noqa: SLF001 - test-only introspection
        finally:
            import asyncio

            asyncio.run(provider.aclose())

    def test_unsupported_provider_raises_instead_of_falling_back_to_extractive(self) -> None:
        # Bypasses TutorModelSettings' own validator (which would already
        # reject this) to prove the composition root has its own independent
        # guard and never silently defaults to extractive.
        settings = TutorModelSettings.model_construct(
            tutor_model_provider="not_a_real_provider",
            tutor_model_base_url="http://localhost:11434/v1",
            tutor_model_api_key="",
            tutor_model_name="",
            tutor_model_timeout_seconds=60.0,
            tutor_model_thinking_level="low",
        )
        with pytest.raises(ValueError, match="Unsupported tutor_model_provider"):
            _build_tutor_model(settings)


class TestTutorModelLifespanClose:
    """Mirrors the exact `finally:` block `create_app`'s lifespan runs on
    shutdown - `_close_tutor_model` is the extracted, directly-testable
    function it calls."""

    async def test_closes_an_owned_ollama_cloud_client(self) -> None:
        adapter = OllamaCloudTutorAdapter(api_key="test-only-key", model_name="gpt-oss:20b")
        owned_client = adapter._client  # noqa: SLF001 - test-only introspection

        await _close_tutor_model(adapter)

        assert owned_client.is_closed

    async def test_does_not_close_an_injected_ollama_cloud_client(self) -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
        adapter = OllamaCloudTutorAdapter(api_key="test-only-key", model_name="gpt-oss:20b", client=client)

        await _close_tutor_model(adapter)

        assert not client.is_closed
        await client.aclose()

    async def test_closes_an_owned_openai_compatible_client(self) -> None:
        adapter = OpenAICompatibleTutorAdapter(
            base_url="http://localhost:11434/v1", api_key="", model_name="llama3"
        )
        owned_client = adapter._client  # noqa: SLF001 - test-only introspection

        await _close_tutor_model(adapter)

        assert owned_client.is_closed

    async def test_does_not_close_an_injected_openai_compatible_client(self) -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
        adapter = OpenAICompatibleTutorAdapter(
            base_url="http://localhost:11434/v1", api_key="", model_name="llama3", client=client
        )

        await _close_tutor_model(adapter)

        assert not client.is_closed
        await client.aclose()

    async def test_extractive_tutor_has_nothing_to_close(self) -> None:
        # DeterministicExtractiveTutor owns no HTTP client - closing it must
        # be a safe no-op, never an AttributeError from a missing aclose().
        await _close_tutor_model(DeterministicExtractiveTutor())


class TestKnowledgeSufficiencyGateComposition:
    """Unit tests for `app_factory._build_knowledge_sufficiency_gate`
    (Phase E1). Mirrors `TestProviderDispatch` above: the enabled/disabled
    choice is made once, here, in composition - never as a scattered flag
    check inside `GroundedAITutorService`."""

    def test_default_settings_build_disabled_gate(self) -> None:
        gate = _build_knowledge_sufficiency_gate(KnowledgeSufficiencySettings(_env_file=None))
        assert isinstance(gate, DisabledKnowledgeSufficiencyGate)

    def test_explicitly_disabled_builds_disabled_gate(self) -> None:
        gate = _build_knowledge_sufficiency_gate(
            KnowledgeSufficiencySettings(_env_file=None, tutor_knowledge_sufficiency_gate_enabled=False)
        )
        assert isinstance(gate, DisabledKnowledgeSufficiencyGate)

    def test_enabled_builds_rule_based_gate_with_configured_thresholds(self) -> None:
        settings = KnowledgeSufficiencySettings(
            _env_file=None,
            tutor_knowledge_sufficiency_gate_enabled=True,
            tutor_knowledge_sufficiency_min_vector_score=0.6,
            tutor_knowledge_sufficiency_min_lexical_score=0.1,
            tutor_knowledge_sufficiency_min_context_metadata_score=0.8,
        )
        gate = _build_knowledge_sufficiency_gate(settings)
        assert isinstance(gate, RuleBasedKnowledgeSufficiencyGate)
        assert gate._minimum_vector_score == 0.6  # noqa: SLF001 - test-only introspection
        assert gate._minimum_lexical_score == 0.1  # noqa: SLF001
        assert gate._minimum_context_metadata_score == 0.8  # noqa: SLF001

    def test_enabled_gate_uses_calibrated_defaults_when_not_overridden(self) -> None:
        settings = KnowledgeSufficiencySettings(_env_file=None, tutor_knowledge_sufficiency_gate_enabled=True)
        gate = _build_knowledge_sufficiency_gate(settings)
        assert isinstance(gate, RuleBasedKnowledgeSufficiencyGate)
        assert gate._minimum_vector_score == 0.52  # noqa: SLF001
        assert gate._minimum_lexical_score == 0.05  # noqa: SLF001
        assert gate._minimum_context_metadata_score == 0.90  # noqa: SLF001
