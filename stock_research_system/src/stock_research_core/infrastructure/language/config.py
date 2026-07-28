"""Configuration for the shared, cross-cutting language service (Phase G2E2A).

Reads settings from environment variables (and an optional `.env` file),
matching `infrastructure.ai_tutor.config.TutorModelSettings`. Importing
this module never makes a network request - it only describes how the
language service *would* be configured.

`HEBREW_QUERY_BRIDGE_ENABLED=false` (the default) is the safe,
rollback-neutral setting - deploying this feature's code alone must not
change any existing (English) behavior. It is the **single, shared** kill
switch for every consumer of the bridge - `GroundedAITutorService`, the
LangGraph learning coach (Tutor and Coach share one flag; there is
deliberately no separate "Tutor-only" name), and
`LiveResearchRunExecutionJobHandler` (both the API process and the Celery
worker) - each checks its own `language_service_enabled` flag *before*
calling `detect_language()` at all, so a disabled deployment runs zero
new code for any question, English or otherwise.

Phase G2D2 note: this settings class, `build_language_service()` below,
and the rest of `application.language`/`infrastructure.language` are the
one shared language-service surface - G2D2's Coach research-resume work
must reuse these, never define a second flag, settings class, or
provider adapter. See the `application/language/` and
`infrastructure/language/` module docstrings for the full reuse list.
"""

from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_SUPPORTED_LANGUAGE_SERVICE_PROVIDERS = frozenset({"unavailable", "llm_backed"})

DEFAULT_LANGUAGE_SERVICE_TIMEOUT_SECONDS = 15.0


class LanguageServiceSettings(BaseSettings):
    """Whether the shared Hebrew translation bridge is enabled, and how
    to configure its translation-capable provider.

    `language_service_provider="unavailable"` (the default) requires no
    API key and no network access - `detect_language()`/`localize()`
    still work (pure, free), but `translate_to_english_query()` always
    fails, so every consumer degrades to its documented
    translation-failure fallback.

    `"llm_backed"` calls a configured chat-completions-shaped endpoint
    with a short, distinct "translate, do not answer" prompt.
    `language_service_base_url`/`_api_key`/`_model_name` are **optional
    overrides** - when left blank, `build_language_service()` reuses the
    already-configured server-side `TutorModelSettings` credentials
    (whichever of `openai_compatible`/`ollama_cloud` is configured)
    rather than requiring a second copy of the same API key. Supplying
    these three fields here is only needed to point translation at a
    *different* endpoint than the Tutor's own model.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    hebrew_query_bridge_enabled: bool = False
    language_service_provider: str = "unavailable"
    language_service_base_url: str = ""
    language_service_api_key: str = ""
    language_service_model_name: str = ""
    language_service_timeout_seconds: float = DEFAULT_LANGUAGE_SERVICE_TIMEOUT_SECONDS

    @model_validator(mode="after")
    def _validate_provider_configuration(self) -> "LanguageServiceSettings":
        if self.language_service_provider not in _SUPPORTED_LANGUAGE_SERVICE_PROVIDERS:
            raise ValueError(
                f"Unsupported language_service_provider {self.language_service_provider!r}; "
                f"must be one of {sorted(_SUPPORTED_LANGUAGE_SERVICE_PROVIDERS)}"
            )
        # Credential completeness is intentionally NOT validated here:
        # `language_service_base_url`/`_api_key`/`_model_name` are each
        # independently optional overrides, resolved together with
        # `TutorModelSettings` (a settings class this one has no
        # visibility into) by `build_language_service()`, which raises
        # `LanguageServiceConfigurationError` if enabled with no
        # resolvable credential anywhere. Validating partial overrides
        # here would incorrectly reject the common, intended case of
        # "reuse the Tutor's own configured provider."
        return self
