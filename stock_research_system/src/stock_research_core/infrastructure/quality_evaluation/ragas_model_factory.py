"""Builds the RAGAS evaluator LLM and embeddings adapter from
`QualityEvaluationSettings` - the *only* other file (besides
`ragas_adapter.py`) allowed to import `ragas`.

Nothing here runs at import time: no HTTP client is opened and no model
is downloaded until `build_ragas_llm`/`build_ragas_embeddings` is
actually called by the composition root, and only when
`ragas_enabled=True`.
"""

from __future__ import annotations

from typing import Any

from stock_research_core.application.ai_tutor.ports import EmbeddingPort
from stock_research_core.infrastructure.quality_evaluation.config import QualityEvaluationSettings


def build_ragas_llm(settings: QualityEvaluationSettings) -> Any:
    """An `InstructorBaseRagasLLM` backed by an OpenAI-compatible client
    pointed at `settings.ragas_evaluator_base_url` - a self-hosted or
    third-party endpoint, deliberately never the production tutor's own
    provider object (spec section 4: evaluator config is independent of
    the tutor's)."""
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory

    if not settings.ragas_evaluator_model:
        raise ValueError("RAGAS_EVALUATOR_MODEL must be set when RAGAS_ENABLED=true")

    client = AsyncOpenAI(
        base_url=settings.ragas_evaluator_base_url or None, api_key=settings.ragas_evaluator_api_key or "not-required",
        timeout=settings.ragas_timeout_seconds, max_retries=settings.ragas_max_retries,
    )
    return llm_factory(model=settings.ragas_evaluator_model, provider="openai", client=client)


def build_ragas_embeddings(embedding_provider: EmbeddingPort) -> Any:
    """Wraps FinQuest's existing `EmbeddingPort` to satisfy RAGAS's
    `BaseRagasEmbedding` - the embedding model that produced FinQuest's
    knowledge-base vectors is reused as-is, never a second,
    independently configured embedding provider. Defined inside this
    function (not at module scope) so `ragas.embeddings.base` is only
    ever imported here, never at this module's own import time."""
    from ragas.embeddings.base import BaseRagasEmbedding

    class _EmbeddingPortRagasAdapter(BaseRagasEmbedding):
        def __init__(self, port: EmbeddingPort) -> None:
            self._port = port

        async def aembed_text(self, text: str, **kwargs: Any) -> list[float]:
            vectors = await self._port.embed_texts([text])
            return list(vectors[0])

        async def aembed_texts(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
            vectors = await self._port.embed_texts(texts)
            return [list(vector) for vector in vectors]

        def embed_text(self, text: str, **kwargs: Any) -> list[float]:
            raise NotImplementedError("Only the async embedding path is used - RAGAS metrics here are always awaited.")

        def embed_texts(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
            raise NotImplementedError("Only the async embedding path is used - RAGAS metrics here are always awaited.")

    return _EmbeddingPortRagasAdapter(embedding_provider)
