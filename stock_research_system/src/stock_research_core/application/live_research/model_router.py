"""`ResearchModelRouter`: deterministic (no LLM chooses) provider
selection for Live Research grounded synthesis (spec G2D2/H1 correction
pass, section 6) - structurally parallel to `ai_tutor.model_router.
TutorModelRouter`, but never interchangeable with it: this router is
typed to `ResearchSynthesisRequest`/`ResearchSynthesisResult` and the
`EvidenceItem`-scoped citation space, never Tutor knowledge chunks.

Ollama (primary) is always tried first; OpenAI (secondary) is only ever
consulted as a bounded fallback when Ollama fails and OpenAI is
explicitly enabled - the same "never left ungrounded, optional fallback
only" contract `TutorModelRouter` already established.
"""

from __future__ import annotations

from stock_research_core.application.exceptions import ResearchModelProviderError
from stock_research_core.application.live_research.ports import ResearchModelPort
from stock_research_core.application.live_research.synthesis_models import (
    ResearchModelProviderType,
    ResearchSynthesisRequest,
    ResearchSynthesisResult,
)


class ResearchModelRouter:
    """Wraps a required Ollama-primary `ResearchModelPort` and an
    optional OpenAI-secondary `ResearchModelPort`, and is itself a
    `ResearchModelPort` - so it slots into `synthesize_research_response`
    exactly like any single adapter."""

    def __init__(
        self, *, primary: ResearchModelPort, secondary: ResearchModelPort | None = None,
        secondary_enabled: bool = False,
    ) -> None:
        self._primary = primary
        self._secondary = secondary
        self._secondary_enabled = secondary_enabled and secondary is not None
        self.provider_type = getattr(primary, "provider_type", ResearchModelProviderType.OLLAMA_CLOUD)

    async def generate(self, request: ResearchSynthesisRequest) -> ResearchSynthesisResult:
        try:
            return await self._primary.generate(request)
        except ResearchModelProviderError:
            if self._secondary_enabled:
                assert self._secondary is not None
                return await self._secondary.generate(request)
            raise
