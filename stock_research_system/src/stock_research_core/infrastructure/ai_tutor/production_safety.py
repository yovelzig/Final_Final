"""Production safety checks for the configured embedding provider
(Phase 11 stabilization ss3.1).

`deterministic_fake` is a network-free, no-model-download adapter meant
for tests (always allowed) and development (allowed, with a warning) -
never an accidental production default. Production startup refuses it
unless `ALLOW_FAKE_EMBEDDINGS_IN_PRODUCTION=true` is explicitly set.
"""

from __future__ import annotations

import importlib.util

from stock_research_core.application.exceptions import StockResearchError
from stock_research_core.infrastructure.ai_tutor.config import EmbeddingSettings
from stock_research_core.infrastructure.operations.config import FinquestEnv, OperationsSettings

FAKE_PROVIDER_NAME = "deterministic_fake"


class UnsafeEmbeddingProviderConfigurationError(StockResearchError):
    """`EMBEDDING_PROVIDER=deterministic_fake` was configured in production
    without the explicit `ALLOW_FAKE_EMBEDDINGS_IN_PRODUCTION=true` override."""


def assert_embedding_provider_production_safe(
    *, embedding_settings: EmbeddingSettings, operations_settings: OperationsSettings
) -> None:
    """Raise `UnsafeEmbeddingProviderConfigurationError` if `deterministic_fake`
    is configured in production without an explicit override. Called once at
    process startup (API and worker composition roots) - never silently
    downgrades or substitutes a different provider."""
    if operations_settings.finquest_env != FinquestEnv.PRODUCTION:
        return
    if embedding_settings.embedding_provider != FAKE_PROVIDER_NAME:
        return
    if operations_settings.allow_fake_embeddings_in_production:
        return
    raise UnsafeEmbeddingProviderConfigurationError(
        f"EMBEDDING_PROVIDER={FAKE_PROVIDER_NAME} is not allowed with FINQUEST_ENV=production. "
        "Configure a real embedding provider (EMBEDDING_PROVIDER=sentence_transformer, built with "
        "the `ai` Docker profile/image), or set ALLOW_FAKE_EMBEDDINGS_IN_PRODUCTION=true if this is "
        "a deliberate, reviewed exception."
    )


def is_production_approved(*, embedding_settings: EmbeddingSettings, operations_settings: OperationsSettings) -> bool:
    """Whether the currently configured provider is safe for
    `FINQUEST_ENV=production` - used by readiness reporting, independent
    of whether the process is actually running in production right now."""
    if embedding_settings.embedding_provider != FAKE_PROVIDER_NAME:
        return True
    return operations_settings.allow_fake_embeddings_in_production


def check_embedding_model_initializable(embedding_settings: EmbeddingSettings) -> bool:
    """A bounded, network-free check (package importability only - never a
    model download) of whether the configured provider *could* initialize.
    Safe to call from `/ready`; never called from `/health`."""
    if embedding_settings.embedding_provider == FAKE_PROVIDER_NAME:
        return True
    if embedding_settings.embedding_provider == "sentence_transformer":
        return importlib.util.find_spec("sentence_transformers") is not None
    return False


def describe_embedding_provider_status(
    *, embedding_settings: EmbeddingSettings, operations_settings: OperationsSettings
) -> dict[str, object]:
    warnings: list[str] = []
    if embedding_settings.embedding_provider == FAKE_PROVIDER_NAME and operations_settings.finquest_env == FinquestEnv.DEVELOPMENT:
        warnings.append(
            "EMBEDDING_PROVIDER=deterministic_fake is in use in development - fine for local "
            "iteration, but production startup will refuse this without an explicit override."
        )
    return {
        "provider": embedding_settings.embedding_provider,
        "environment": operations_settings.finquest_env.value,
        "production_approved": is_production_approved(
            embedding_settings=embedding_settings, operations_settings=operations_settings
        ),
        "initializable": check_embedding_model_initializable(embedding_settings),
        "warnings": warnings,
    }
