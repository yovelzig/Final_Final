"""`EvaluationCachePort` implementation - caches RAGAS sample results by
a stable key (case/response/context hash + metric version + evaluator
provider/model, built by the caller - never a secret). In-memory only
for now: RAGAS mode is not enabled by default this phase (spec section
4), so there is no cross-process cache traffic yet to justify a Redis-
backed implementation; the port boundary is what matters for a future
swap.
"""

from __future__ import annotations

import hashlib

from stock_research_core.application.quality_evaluation.models import RagasSampleResult


def build_cache_key(
    *, case_hash: str, response_hash: str, context_hash: str, metric_version: str, evaluator_provider: str,
    evaluator_model: str,
) -> str:
    canonical = "|".join([case_hash, response_hash, context_hash, metric_version, evaluator_provider, evaluator_model])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class InMemoryEvaluationCache:
    def __init__(self) -> None:
        self._store: dict[str, RagasSampleResult] = {}

    async def get(self, *, cache_key: str) -> RagasSampleResult | None:
        return self._store.get(cache_key)

    async def set(self, *, cache_key: str, result: RagasSampleResult) -> None:
        self._store[cache_key] = result
