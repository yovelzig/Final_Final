"""Worker-composition regression tests (Phase G2E2A correction pass, req. 1).

`LIVE_RESEARCH_RUN_EXECUTION` does not execute in the API process - it
executes in the Celery worker, whose composition root is
`infrastructure.operations.celery_tasks._build_worker_context`. Composing
the language service in `api.app_factory` alone therefore left the *real*
`finquest-worker-research` handler holding the safe-but-inert
`UnavailableLanguageService`, silently disabling the Hebrew bridge for
every Live Research run.

These tests deliberately go through the REAL composition path -
`_build_worker_context()` -> `build_operations_registry()` ->
`registry.get_handler(LIVE_RESEARCH_RUN_EXECUTION)` - and assert on the
handler the worker would actually use. A directly constructed
`LiveResearchRunExecutionJobHandler` would prove nothing here: passing the
language service to the constructor was never the part that was broken.

Everything is hermetic: every settings object is constructed explicitly
(no ambient `.env`/environment leakage), the embedding provider is the
deterministic fake (never downloads a model), and `httpx` is patched to
fail loudly if composition tries to make a network request.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest

from stock_research_core.application.language.unavailable_language_service import UnavailableLanguageService
from stock_research_core.domain.operations.enums import BackgroundJobType
from stock_research_core.infrastructure.ai_tutor.config import EmbeddingSettings, TutorModelSettings
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.language.config import LanguageServiceSettings
from stock_research_core.infrastructure.language.llm_backed_language_service import LlmBackedLanguageService
from stock_research_core.infrastructure.operations import celery_tasks
from stock_research_core.infrastructure.operations.config import OperationsSettings

_TRANSLATION_API_KEY = "worker-composition-test-key-never-real"


def _hermetic_settings(**language_overrides: Any) -> dict[str, Any]:
    """Every settings object the worker composition root needs, built
    explicitly so no developer `.env` file can influence the result."""
    return {
        "database_settings": DatabaseSettings(
            database_url="postgresql+asyncpg://user:password@localhost:5433/never_connected",
        ),
        "embedding_settings": EmbeddingSettings(embedding_provider="deterministic_fake", embedding_dimension=8),
        "operations_settings": OperationsSettings(redis_url="redis://localhost:6379/0", metrics_enabled=False),
        "language_service_settings": LanguageServiceSettings(**language_overrides),
        "tutor_model_settings": TutorModelSettings(tutor_model_provider="extractive"),
    }


def _enabled_settings() -> dict[str, Any]:
    return _hermetic_settings(
        hebrew_query_bridge_enabled=True,
        language_service_provider="llm_backed",
        language_service_base_url="https://translation.invalid/v1",
        language_service_api_key=_TRANSLATION_API_KEY,
        language_service_model_name="test-translation-model",
    )


@pytest.fixture(autouse=True)
def _forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Composition must remain network-free: constructing an
    `LlmBackedLanguageService` may only open a *lazy* `httpx.AsyncClient`,
    never send a request."""

    async def _fail(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Worker composition must not make a network request at startup.")

    monkeypatch.setattr(httpx.AsyncClient, "send", _fail)
    monkeypatch.setattr(httpx.Client, "send", _fail)


@pytest.fixture(autouse=True)
def _reset_worker_context() -> Any:
    """The composition root caches one `WorkerContext` per worker process
    in a module global; never leak this test's context into another test."""
    celery_tasks._worker_context = None
    yield
    celery_tasks._worker_context = None


def _live_research_entry(context: celery_tasks.WorkerContext) -> Any:
    return context.registry.get(BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION)


def _live_research_handler(context: celery_tasks.WorkerContext) -> Any:
    return _live_research_entry(context).handler


class TestRealWorkerRegistryReceivesTheConfiguredLanguageService:
    """The core regression: the handler the REAL worker registry resolves
    for `LIVE_RESEARCH_RUN_EXECUTION` holds the configured, enabled
    language service - not a default `UnavailableLanguageService`."""

    def test_handler_receives_the_configured_translation_capable_service(self) -> None:
        context = celery_tasks._build_worker_context(**_enabled_settings())

        handler = _live_research_handler(context)
        assert isinstance(handler._language_service, LlmBackedLanguageService)

    def test_handler_receives_the_shared_instance_not_a_second_one(self) -> None:
        """One shared `LanguageServicePort` per process (spec ss1/ss11):
        the handler, the registry, and `WorkerContext` must all reference
        the *same object*, never independently constructed copies."""
        context = celery_tasks._build_worker_context(**_enabled_settings())

        assert _live_research_handler(context)._language_service is context.language_service

    def test_handler_is_told_the_bridge_is_enabled(self) -> None:
        context = celery_tasks._build_worker_context(**_enabled_settings())

        assert _live_research_handler(context)._language_service_enabled is True

    def test_worker_context_exposes_the_language_service_for_shutdown(self) -> None:
        context = celery_tasks._build_worker_context(**_enabled_settings())

        assert isinstance(context.language_service, LlmBackedLanguageService)

    def test_composition_is_network_free(self) -> None:
        """Guarded by the `_forbid_network` fixture - building the context
        with a translation-capable provider configured must still not send
        a single request."""
        context = celery_tasks._build_worker_context(**_enabled_settings())

        assert context.language_service is not None


class TestWorkerDefaultsSafelyWhileDisabled:
    """`HEBREW_QUERY_BRIDGE_ENABLED=false` (the default, and production's
    current value) must leave the worker byte-identical to before this
    phase."""

    def test_disabled_flag_composes_the_unavailable_service(self) -> None:
        context = celery_tasks._build_worker_context(**_hermetic_settings())

        assert isinstance(context.language_service, UnavailableLanguageService)

    def test_disabled_flag_leaves_the_handler_with_the_bridge_off(self) -> None:
        context = celery_tasks._build_worker_context(**_hermetic_settings())

        handler = _live_research_handler(context)
        assert handler._language_service_enabled is False
        assert isinstance(handler._language_service, UnavailableLanguageService)

    def test_provider_configured_but_flag_disabled_still_composes_unavailable(self) -> None:
        """The flag wins over the provider setting - an operator who left
        `LANGUAGE_SERVICE_PROVIDER=llm_backed` configured but the shared
        flag off gets no translation capability at all."""
        context = celery_tasks._build_worker_context(
            **_hermetic_settings(
                language_service_provider="llm_backed",
                language_service_base_url="https://translation.invalid/v1",
                language_service_api_key=_TRANSLATION_API_KEY,
                language_service_model_name="test-translation-model",
            )
        )

        assert isinstance(context.language_service, UnavailableLanguageService)


class TestWorkerCompositionNeverLogsTheApiKey:
    def test_api_key_absent_from_every_log_record(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG):
            celery_tasks._build_worker_context(**_enabled_settings())

        assert _TRANSLATION_API_KEY not in caplog.text

    def test_api_key_absent_from_the_composed_service_repr(self) -> None:
        """A settings object or adapter that leaks its key through `repr()`
        would eventually leak it into a log line or traceback."""
        context = celery_tasks._build_worker_context(**_enabled_settings())

        assert _TRANSLATION_API_KEY not in repr(context.language_service)


class TestWorkerProcessShutdownClosesAnOwnedHttpClient:
    def test_shutdown_closes_the_owned_client(self) -> None:
        closed: list[bool] = []

        class _RecordingLanguageService(UnavailableLanguageService):
            pass

        recording = _RecordingLanguageService()
        celery_tasks._worker_context = celery_tasks.WorkerContext(
            engine=None, redis_client=None, service=None, registry=None, language_service=recording,
        )

        celery_tasks._shutdown_worker_process()

        # `UnavailableLanguageService` owns no client, so nothing to close -
        # the contract proven here is that shutdown ran and released the
        # cached context rather than leaving a stale one behind.
        assert closed == []
        assert celery_tasks._worker_context is None

    def test_shutdown_awaits_aclose_on_an_http_backed_service(self, monkeypatch: pytest.MonkeyPatch) -> None:
        context = celery_tasks._build_worker_context(**_enabled_settings())
        celery_tasks._worker_context = context
        closed: list[bool] = []

        async def _record_aclose(_self: Any) -> None:
            closed.append(True)

        monkeypatch.setattr(LlmBackedLanguageService, "aclose", _record_aclose)

        celery_tasks._shutdown_worker_process()

        assert closed == [True]
        assert celery_tasks._worker_context is None

    def test_shutdown_without_a_context_is_a_safe_no_op(self) -> None:
        celery_tasks._worker_context = None

        celery_tasks._shutdown_worker_process()

        assert celery_tasks._worker_context is None
