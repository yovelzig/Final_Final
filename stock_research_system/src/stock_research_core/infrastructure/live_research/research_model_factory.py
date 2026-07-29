"""Composition helper for the Live Research grounded-synthesis model
router (spec G2D2/H1 correction pass, section 6) - mirrors `ai_tutor.
model_factory.build_tutor_model`'s shape, but returns `None` (rather
than a deterministic-fallback adapter) when Ollama is unconfigured,
since there is no equivalent "extractive" no-LLM synthesis mode for
Live Research any more - `synthesize_research_response` treats `None`
exactly like a provider failure: a bounded, localized fallback message,
never a fabricated answer.
"""

from __future__ import annotations

from stock_research_core.application.live_research.model_router import ResearchModelRouter
from stock_research_core.application.live_research.ports import ResearchModelPort
from stock_research_core.infrastructure.live_research.config import ResearchModelSettings
from stock_research_core.infrastructure.live_research.ollama_research_synthesis import (
    OllamaResearchSynthesisAdapter,
)
from stock_research_core.infrastructure.live_research.openai_research_synthesis import (
    OpenAIResearchSynthesisAdapter,
)


def build_research_model(settings: ResearchModelSettings) -> ResearchModelPort | None:
    if not settings.research_model_ollama_api_key or not settings.research_model_ollama_model:
        return None

    primary = OllamaResearchSynthesisAdapter(
        base_url=settings.research_model_ollama_base_url, api_key=settings.research_model_ollama_api_key,
        model_name=settings.research_model_ollama_model,
        timeout_seconds=settings.research_model_ollama_timeout_seconds,
        thinking_level=settings.research_model_ollama_thinking_level,
    )
    if not settings.research_model_openai_enabled:
        return primary

    secondary = OpenAIResearchSynthesisAdapter(
        api_key=settings.research_model_openai_api_key, model_name=settings.research_model_openai_model,
        timeout_seconds=settings.research_model_openai_timeout_seconds,
    )
    return ResearchModelRouter(primary=primary, secondary=secondary, secondary_enabled=True)


async def close_research_model(research_model: ResearchModelPort | None) -> None:
    if research_model is None:
        return
    if isinstance(research_model, ResearchModelRouter):
        await close_research_model(research_model._primary)  # noqa: SLF001
        if research_model._secondary is not None:  # noqa: SLF001
            await close_research_model(research_model._secondary)  # noqa: SLF001
        return
    if isinstance(research_model, (OllamaResearchSynthesisAdapter, OpenAIResearchSynthesisAdapter)):
        await research_model.aclose()
