"""Unit tests for `LanguageServiceSettings` (Phase G2E2A) - the single,
shared, feature-gated configuration (`HEBREW_QUERY_BRIDGE_ENABLED`),
disabled by default (spec requirement 12).

Credential completeness (base URL/API key/model name) is deliberately
NOT validated here - see `test_language_composition.py` for that, since
it depends on `TutorModelSettings` reuse, a settings class this one has
no visibility into.
"""

from __future__ import annotations

import pytest

from stock_research_core.infrastructure.language.config import LanguageServiceSettings


def test_disabled_by_default() -> None:
    settings = LanguageServiceSettings(_env_file=None)
    assert settings.hebrew_query_bridge_enabled is False
    assert settings.language_service_provider == "unavailable"


def test_env_var_name_is_the_single_shared_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """`HEBREW_QUERY_BRIDGE_ENABLED` - not a Tutor-only name - since this
    flag also gates the Coach and Live Research paths."""
    monkeypatch.setenv("HEBREW_QUERY_BRIDGE_ENABLED", "true")
    try:
        settings = LanguageServiceSettings(_env_file=None)
        assert settings.hebrew_query_bridge_enabled is True
    finally:
        monkeypatch.delenv("HEBREW_QUERY_BRIDGE_ENABLED", raising=False)


def test_unavailable_provider_requires_no_credentials() -> None:
    settings = LanguageServiceSettings(_env_file=None, hebrew_query_bridge_enabled=True, language_service_provider="unavailable")
    assert settings.hebrew_query_bridge_enabled is True


def test_llm_backed_does_not_require_credentials_at_settings_construction() -> None:
    """Credentials may legitimately come from `TutorModelSettings` reuse
    instead - `LanguageServiceSettings` alone cannot know that, so it
    must not raise here. `build_language_service()` is what enforces
    "some credential must resolve from somewhere"."""
    settings = LanguageServiceSettings(
        _env_file=None, hebrew_query_bridge_enabled=True, language_service_provider="llm_backed",
    )
    assert settings.language_service_base_url == ""


def test_llm_backed_with_full_configuration_is_valid() -> None:
    settings = LanguageServiceSettings(
        _env_file=None, hebrew_query_bridge_enabled=True, language_service_provider="llm_backed",
        language_service_base_url="https://example.internal/v1", language_service_api_key="key",
        language_service_model_name="test-model",
    )
    assert settings.language_service_provider == "llm_backed"


def test_disabled_does_not_require_credentials() -> None:
    settings = LanguageServiceSettings(
        _env_file=None, hebrew_query_bridge_enabled=False, language_service_provider="llm_backed",
    )
    assert settings.hebrew_query_bridge_enabled is False


def test_unsupported_provider_rejected() -> None:
    with pytest.raises(ValueError):
        LanguageServiceSettings(_env_file=None, language_service_provider="google_translate")
