"""The one shared `LanguageServicePort` composition function (Phase G2E2A).

Every process that needs a language service - the API process
(`api.app_factory`), the Celery worker (`infrastructure.operations.celery_tasks`),
and (per Phase G2D2) the Coach research-resume path - must call
`build_language_service()` here rather than re-implementing the
enabled/disabled or provider-selection decision itself. This is what
makes "one shared `LanguageServicePort`, reused, not re-implemented"
(spec ss1/ss11) actually true across processes, not just within one.

Never makes a network call: constructing an `LlmBackedLanguageService`
only opens an `httpx.AsyncClient` (lazy, no connection until first
request) - identical in spirit to `api.app_factory._build_tutor_model`.
"""

from __future__ import annotations

from stock_research_core.application.exceptions import LanguageServiceConfigurationError
from stock_research_core.application.language.ports import LanguageServicePort
from stock_research_core.application.language.unavailable_language_service import UnavailableLanguageService
from stock_research_core.infrastructure.ai_tutor.config import TutorModelSettings
from stock_research_core.infrastructure.language.config import LanguageServiceSettings
from stock_research_core.infrastructure.language.llm_backed_language_service import LlmBackedLanguageService

_REUSABLE_TUTOR_MODEL_PROVIDERS = frozenset({"openai_compatible", "ollama_cloud"})


def build_language_service(
    settings: LanguageServiceSettings, *, tutor_model_settings: TutorModelSettings | None = None,
) -> LanguageServicePort:
    """The one place the enabled/disabled and provider choice is made.

    `HEBREW_QUERY_BRIDGE_ENABLED=false` (the default, and production's
    current value) always returns `UnavailableLanguageService`, regardless
    of `language_service_provider` - deploying this feature's code alone
    never changes existing behavior.

    When enabled with `language_service_provider="llm_backed"`:
    `language_service_base_url`/`_api_key`/`_model_name` are tried first;
    any left blank fall back to the already-configured server-side
    `tutor_model_settings` (`openai_compatible`/`ollama_cloud` only -
    `extractive` has no endpoint to reuse), so a deployment that already
    configured a Tutor LLM provider does not need a second copy of the
    same API key. If nothing resolves, raises
    `LanguageServiceConfigurationError` - an operator who explicitly
    enabled the bridge gets a clear, fail-fast configuration error, never
    a silent `UnavailableLanguageService` substitution.
    """
    if not settings.hebrew_query_bridge_enabled:
        return UnavailableLanguageService()
    if settings.language_service_provider != "llm_backed":
        return UnavailableLanguageService()

    base_url = settings.language_service_base_url
    api_key = settings.language_service_api_key
    model_name = settings.language_service_model_name
    wire_shape = "openai_compatible"

    has_explicit_credentials = bool(base_url and api_key and model_name)
    if not has_explicit_credentials and tutor_model_settings is not None:
        if tutor_model_settings.tutor_model_provider in _REUSABLE_TUTOR_MODEL_PROVIDERS:
            base_url = base_url or tutor_model_settings.tutor_model_base_url
            api_key = api_key or tutor_model_settings.tutor_model_api_key
            model_name = model_name or tutor_model_settings.tutor_model_name
            wire_shape = (
                "ollama_cloud" if tutor_model_settings.tutor_model_provider == "ollama_cloud" else "openai_compatible"
            )

    if not (base_url and api_key and model_name):
        raise LanguageServiceConfigurationError(
            "HEBREW_QUERY_BRIDGE_ENABLED=true with language_service_provider='llm_backed' requires a "
            "base URL, API key, and model name - set LANGUAGE_SERVICE_BASE_URL/_API_KEY/_MODEL_NAME "
            "explicitly, or configure TUTOR_MODEL_PROVIDER=openai_compatible/ollama_cloud so its "
            "credentials can be reused."
        )

    return LlmBackedLanguageService(
        base_url=base_url, api_key=api_key, model_name=model_name, wire_shape=wire_shape,
        timeout_seconds=settings.language_service_timeout_seconds,
    )


async def close_language_service(language_service: LanguageServicePort) -> None:
    """Closes an HTTP-backed language-service adapter's own client on
    process shutdown (API or worker). `UnavailableLanguageService` owns
    no client and is left alone."""
    if isinstance(language_service, LlmBackedLanguageService):
        await language_service.aclose()
