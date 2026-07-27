"""Unit tests for `TutorModelSettings` (Phase D: ollama_cloud provider).

Hermetic: `_env_file=None` is passed everywhere so a real local `.env` (if
one exists) can never leak into these tests, and every ambient
`TUTOR_MODEL_*` OS environment variable is cleared first.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from stock_research_core.infrastructure.ai_tutor.config import TutorModelSettings

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


class TestDefaultProvider:
    def test_default_provider_is_extractive(self) -> None:
        settings = _settings()
        assert settings.tutor_model_provider == "extractive"

    def test_extractive_does_not_require_cloud_configuration(self) -> None:
        settings = _settings(tutor_model_provider="extractive")
        assert settings.tutor_model_api_key == ""
        assert settings.tutor_model_name == ""

    def test_default_thinking_level_is_low(self) -> None:
        settings = _settings()
        assert settings.tutor_model_thinking_level == "low"


class TestOpenAiCompatibleProviderUnaffected:
    def test_openai_compatible_requires_no_new_field(self) -> None:
        settings = _settings(
            tutor_model_provider="openai_compatible",
            tutor_model_base_url="http://localhost:11434/v1",
            tutor_model_name="llama3",
        )
        assert settings.tutor_model_provider == "openai_compatible"


class TestOllamaCloudProviderValidation:
    def _valid_kwargs(self) -> dict:
        return {
            "tutor_model_provider": "ollama_cloud",
            "tutor_model_base_url": "https://ollama.com/api",
            "tutor_model_api_key": "test-only-key",
            "tutor_model_name": "gpt-oss:20b",
        }

    def test_valid_ollama_cloud_configuration_accepted(self) -> None:
        settings = _settings(**self._valid_kwargs())
        assert settings.tutor_model_provider == "ollama_cloud"
        assert settings.tutor_model_base_url == "https://ollama.com/api"

    def test_missing_api_key_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["tutor_model_api_key"] = ""
        with pytest.raises(ValidationError, match="tutor_model_api_key"):
            _settings(**kwargs)

    def test_missing_model_name_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["tutor_model_name"] = ""
        with pytest.raises(ValidationError, match="tutor_model_name"):
            _settings(**kwargs)

    def test_non_https_base_url_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["tutor_model_base_url"] = "http://ollama.com/api"
        with pytest.raises(ValidationError, match="https"):
            _settings(**kwargs)

    def test_default_base_url_constant_is_https(self) -> None:
        # The recommended default (documented in .env.example / Phase D spec)
        # must itself satisfy the HTTPS requirement.
        from stock_research_core.infrastructure.ai_tutor.ollama_cloud_tutor import (
            DEFAULT_OLLAMA_CLOUD_BASE_URL,
        )

        kwargs = self._valid_kwargs()
        kwargs["tutor_model_base_url"] = DEFAULT_OLLAMA_CLOUD_BASE_URL
        settings = _settings(**kwargs)
        assert settings.tutor_model_base_url.startswith("https://")


class TestInvalidProviderName:
    def test_unknown_provider_name_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Unsupported tutor_model_provider"):
            _settings(tutor_model_provider="ollama")  # not ollama_cloud

    def test_typo_provider_name_does_not_silently_fall_back_to_extractive(self) -> None:
        with pytest.raises(ValidationError):
            _settings(tutor_model_provider="EXTRACTIVE")  # case-sensitive, not the same string
