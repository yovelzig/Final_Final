"""Shared `TutorModelPort`/`KnowledgeSufficiencyGatePort` composition,
used identically by `api.app_factory` and (spec G2D2)
`infrastructure.operations.celery_tasks`'s coach-worker composition -
extracted so the tutor-model-provider switch and the sufficiency-gate
enabled/disabled default never drift between the two.
"""

from __future__ import annotations

from stock_research_core.application.ai_tutor.model_router import TutorModelRouter
from stock_research_core.application.ai_tutor.ports import KnowledgeSufficiencyGatePort, TutorModelPort
from stock_research_core.application.ai_tutor.sufficiency import (
    DisabledKnowledgeSufficiencyGate,
    RuleBasedKnowledgeSufficiencyGate,
)
from stock_research_core.infrastructure.ai_tutor.config import (
    KnowledgeSufficiencySettings,
    OpenAIReasoningSettings,
    TutorModelSettings,
)
from stock_research_core.infrastructure.ai_tutor.extractive_tutor import DeterministicExtractiveTutor
from stock_research_core.infrastructure.ai_tutor.ollama_cloud_tutor import OllamaCloudTutorAdapter
from stock_research_core.infrastructure.ai_tutor.openai_compatible_tutor import OpenAICompatibleTutorAdapter
from stock_research_core.infrastructure.ai_tutor.openai_reasoning_tutor import OpenAIReasoningTutorAdapter


def _build_primary_tutor_model(settings: TutorModelSettings) -> TutorModelPort:
    if settings.tutor_model_provider == "extractive":
        return DeterministicExtractiveTutor()
    if settings.tutor_model_provider == "openai_compatible":
        return OpenAICompatibleTutorAdapter(
            base_url=settings.tutor_model_base_url, api_key=settings.tutor_model_api_key,
            model_name=settings.tutor_model_name, timeout_seconds=settings.tutor_model_timeout_seconds,
        )
    if settings.tutor_model_provider == "ollama_cloud":
        return OllamaCloudTutorAdapter(
            base_url=settings.tutor_model_base_url, api_key=settings.tutor_model_api_key,
            model_name=settings.tutor_model_name, timeout_seconds=settings.tutor_model_timeout_seconds,
            thinking_level=settings.tutor_model_thinking_level,
        )
    # `TutorModelSettings`'s own validator already rejects any other value at
    # construction time - this branch only guards against a future settings
    # change that weakens that validation, never silently falling back to
    # `extractive`.
    raise ValueError(f"Unsupported tutor_model_provider {settings.tutor_model_provider!r}")


def build_tutor_model(
    settings: TutorModelSettings, *, openai_reasoning_settings: OpenAIReasoningSettings | None = None,
) -> TutorModelPort:
    """Builds the primary tutor-model adapter from `settings` exactly as
    before, then - only when `openai_reasoning_settings` is provided and
    `openai_reasoning_enabled=true` - wraps it in a `TutorModelRouter`
    with the optional OpenAI reasoning adapter as the secondary. Every
    existing composition site that does not pass
    `openai_reasoning_settings` (or passes one with the flag off) gets
    back exactly the primary adapter, unchanged, per Phase E1's
    rollback-neutral-default convention."""
    primary = _build_primary_tutor_model(settings)
    if openai_reasoning_settings is None or not openai_reasoning_settings.openai_reasoning_enabled:
        return primary

    secondary = OpenAIReasoningTutorAdapter(
        api_key=openai_reasoning_settings.openai_api_key,
        model_name=openai_reasoning_settings.openai_reasoning_model,
        timeout_seconds=openai_reasoning_settings.openai_reasoning_timeout_seconds,
        maximum_output_tokens=openai_reasoning_settings.openai_reasoning_max_output_tokens,
    )
    return TutorModelRouter(primary=primary, secondary=secondary, secondary_enabled=True)


def build_knowledge_sufficiency_gate(settings: KnowledgeSufficiencySettings) -> KnowledgeSufficiencyGatePort:
    """The one place the enabled/disabled choice is made - Phase E1's
    `TUTOR_KNOWLEDGE_SUFFICIENCY_GATE_ENABLED=false` default (and
    production's current value) means this always returns the explicit
    `DisabledKnowledgeSufficiencyGate`, so deploying this feature's
    code alone never changes `GroundedAITutorService`'s existing
    behavior."""
    if not settings.tutor_knowledge_sufficiency_gate_enabled:
        return DisabledKnowledgeSufficiencyGate()
    return RuleBasedKnowledgeSufficiencyGate(
        minimum_vector_score=settings.tutor_knowledge_sufficiency_min_vector_score,
        minimum_lexical_score=settings.tutor_knowledge_sufficiency_min_lexical_score,
        minimum_context_metadata_score=settings.tutor_knowledge_sufficiency_min_context_metadata_score,
    )


async def close_tutor_model(tutor_model: TutorModelPort) -> None:
    """Closes an HTTP-backed tutor adapter's own client on shutdown.

    `DeterministicExtractiveTutor` owns no client and is left alone. Each
    HTTP adapter's own `aclose()` only closes a client it constructed itself
    (`_owns_client`) - a client the caller injected is never closed here or
    inside the adapter. A `TutorModelRouter` is unwrapped so both its
    primary and (if present) secondary adapter are each closed the same
    way.
    """
    if isinstance(tutor_model, TutorModelRouter):
        await close_tutor_model(tutor_model._primary)  # noqa: SLF001 - composition-root-only unwrap
        if tutor_model._secondary is not None:  # noqa: SLF001 - composition-root-only unwrap
            await close_tutor_model(tutor_model._secondary)  # noqa: SLF001 - composition-root-only unwrap
        return
    if isinstance(tutor_model, (OpenAICompatibleTutorAdapter, OllamaCloudTutorAdapter, OpenAIReasoningTutorAdapter)):
        await tutor_model.aclose()
