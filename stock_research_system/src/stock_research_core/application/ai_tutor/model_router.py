"""`TutorModelRouter`: deterministic (no LLM chooses) provider selection
between the Ollama-primary tutor model and the optional OpenAI reasoning
adapter (spec G2D2 section 5.A-F, section 10).

Case A ("insufficient knowledge -> no model call") never reaches this
router: `GroundedAITutorService.ask()` already returns its fallback
response from the Knowledge Sufficiency Gate before ever calling
`tutor_model.generate()`, so by the time this router's `generate()` is
invoked, sufficiency has already been confirmed. This router only
implements the remaining cases:

B. Ordinary question -> Ollama primary.
C. Complex question + OpenAI enabled -> OpenAI primary.
D. Ollama failure on an ordinary question + OpenAI enabled -> optional
   OpenAI fallback (never the only path - Ollama is always tried first
   for an ordinary question).
E. OpenAI disabled, or OpenAI itself fails on a complex question ->
   falls back to Ollama, never left ungrounded.
F. `is_complex_question()` is a small, bounded, documented keyword/
   structural heuristic - never a model call itself.
"""

from __future__ import annotations

import re

from stock_research_core.application.ai_tutor.diagnostics import TutorDiagnosticIssueCode, log_tutor_diagnostic
from stock_research_core.application.ai_tutor.models import TutorModelRequest, TutorModelResult
from stock_research_core.application.ai_tutor.ports import TutorModelPort
from stock_research_core.application.exceptions import TutorModelProviderError
from stock_research_core.domain.ai_tutor.enums import TutorProviderType

_COMPLEXITY_PATTERNS = (
    re.compile(r"\b(compare|comparison|versus|vs\.?|trade[- ]off|tradeoff)\b", re.IGNORECASE),
    re.compile(r"\b(why did|what happened|in hindsight|looking back|afterward)\b", re.IGNORECASE),
    re.compile(
        r"\b(sharpe|sortino|drawdown|concentration|hhi|turnover)\b.{0,60}"
        r"\b(sharpe|sortino|drawdown|concentration|hhi|turnover)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(summarize|summary|across (my|all|multiple)|overall)\b", re.IGNORECASE),
    re.compile(r"\b(multiple sources|several (studies|reports|filings)|synthesize)\b", re.IGNORECASE),
)


def is_complex_question(question: str) -> bool:
    """Pure, deterministic, bounded - never an LLM call and never
    consulted to decide *whether* to answer, only *which* configured
    provider answers first."""
    return any(pattern.search(question) for pattern in _COMPLEXITY_PATTERNS)


class TutorModelRouter:
    """Wraps a required Ollama-primary `TutorModelPort` and an optional
    OpenAI-reasoning `TutorModelPort`, and is itself a `TutorModelPort` -
    so it slots into `GroundedAITutorService` exactly like any single
    adapter, with no change to the service's own call sites.

    `provider_type` reflects the primary (Ollama) provider - read by
    `GroundedAITutorService._finalize_refusal`/`_finalize_fallback` for
    bookkeeping on paths that never call a model at all, so it does not
    need to reflect whichever provider a given `generate()` call actually
    used; the returned `TutorModelResult.provider_type` always does.
    """

    def __init__(
        self,
        *,
        primary: TutorModelPort,
        secondary: TutorModelPort | None = None,
        secondary_enabled: bool = False,
    ) -> None:
        self._primary = primary
        self._secondary = secondary
        self._secondary_enabled = secondary_enabled and secondary is not None
        self.provider_type = getattr(primary, "provider_type", TutorProviderType.OLLAMA_CLOUD)

    async def generate(self, request: TutorModelRequest) -> TutorModelResult:
        complex_question = is_complex_question(request.user_question)

        if complex_question and self._secondary_enabled:
            try:
                return await self._secondary.generate(request)
            except TutorModelProviderError:
                log_tutor_diagnostic(
                    provider_type=self._secondary.provider_type,
                    model_name=getattr(self._secondary, "_model_name", "unknown"),
                    attempt_number=1, retrieval_candidate_count=len(request.retrieved_candidates), cited_id_count=0,
                    issue_codes=[TutorDiagnosticIssueCode.PROVIDER_ERROR],
                )
                # Case E: OpenAI failed on a complex question - Ollama is
                # never skipped just because the question was complex.
                return await self._primary.generate(request)

        try:
            return await self._primary.generate(request)
        except TutorModelProviderError:
            if self._secondary_enabled:
                # Case D: Ollama failed on an ordinary question - optional
                # bounded OpenAI fallback, only when explicitly enabled.
                return await self._secondary.generate(request)
            raise
