"""Hybrid (vector + lexical + metadata) knowledge retrieval, satisfying
`KnowledgeRetrieverPort`.

Depends only on `KnowledgeRepositoryPort` (via the Unit of Work) and
`EmbeddingPort` - no SQLAlchemy, pgvector, or sentence-transformers
import here. The actual pgvector similarity search and PostgreSQL
full-text search live in
`infrastructure.database.repositories.knowledge_repository.SqlAlchemyKnowledgeRepository
.hybrid_search`; this module only orchestrates the query and shapes the
audit record.

`TutorRetrievalRun.conversation_id` is not known here (`retrieve()`'s
signature, per the spec's `KnowledgeRetrieverPort` Protocol, only takes
`query`/`context`/`top_k` - no conversation ID) - it is constructed with
a placeholder `UUID(int=0)` and rewritten by `GroundedAITutorService`
before persisting, the same "placeholder then rewrite" convention
already used for `PortfolioDecisionJournalEntry.learner_id` in
`cli/virtual_portfolio.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from stock_research_core.application.ai_tutor.models import RetrievalCandidate, TutorContext
from stock_research_core.application.ai_tutor.ports import EmbeddingPort
from stock_research_core.domain.ai_tutor.enums import KnowledgeSourceType, RetrievalMethod, TutorContextType
from stock_research_core.domain.ai_tutor.models import TutorRetrievalRun
from stock_research_core.domain.models import utc_now

HYBRID_RETRIEVAL_VERSION = "hybrid-retrieval-v1"
DEFAULT_TOP_K = 8
DEFAULT_CANDIDATE_POOL_SIZE = 40
_MAX_STORED_QUERY_LENGTH = 2000

Clock = Callable[[], datetime]


class HybridKnowledgeRetriever:
    """Reciprocal-rank-fusion hybrid retriever satisfying `KnowledgeRetrieverPort`."""

    retrieval_policy_version = HYBRID_RETRIEVAL_VERSION

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], Any],
        embedding_provider: EmbeddingPort,
        clock: Clock = utc_now,
        candidate_pool_size: int = DEFAULT_CANDIDATE_POOL_SIZE,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._embedding_provider = embedding_provider
        self._clock = clock
        self._candidate_pool_size = candidate_pool_size

    async def retrieve(
        self, *, query: str, context: TutorContext, top_k: int = DEFAULT_TOP_K
    ) -> tuple[TutorRetrievalRun, list[RetrievalCandidate]]:
        cutoff = context.knowledge_cutoff_at or self._clock()

        query_embedding: list[float] | None = None
        if query.strip():
            vectors = await self._embedding_provider.embed_texts([query])
            query_embedding = vectors[0] if vectors else None

        portfolio_context_code = None
        raw_code = context.structured_context.get("portfolio_context_code")
        if isinstance(raw_code, str):
            portfolio_context_code = raw_code

        async with self._unit_of_work_factory() as uow:
            candidates, candidate_count = await uow.knowledge.hybrid_search(
                query_embedding=query_embedding,
                embedding_model=self._embedding_provider.model_name if query_embedding is not None else None,
                embedding_version=(
                    self._embedding_provider.embedding_version if query_embedding is not None else None
                ),
                lexical_query=query,
                top_k=top_k,
                candidate_pool_size=self._candidate_pool_size,
                approved_only=True,
                language="en",
                skill_ids=context.target_skill_ids or None,
                lesson_id=context.lesson_id,
                exercise_id=context.exercise_id,
                scenario_id=context.scenario_id,
                portfolio_context_code=portfolio_context_code,
                knowledge_cutoff_at=cutoff,
            )

        candidates = self._apply_exercise_answer_leakage_guard(candidates, context)

        run = TutorRetrievalRun(
            conversation_id=UUID(int=0),
            query_text=query[:_MAX_STORED_QUERY_LENGTH],
            method=RetrievalMethod.HYBRID,
            top_k=top_k,
            knowledge_cutoff_at=cutoff,
            retrieval_policy_version=self.retrieval_policy_version,
            embedding_model=self._embedding_provider.model_name,
            embedding_version=self._embedding_provider.embedding_version,
            candidate_count=candidate_count,
            returned_chunk_ids=[candidate.chunk.chunk_id for candidate in candidates],
            returned_scores=[candidate.combined_score for candidate in candidates],
        )
        return run, candidates

    @staticmethod
    def _apply_exercise_answer_leakage_guard(
        candidates: list[RetrievalCandidate], context: TutorContext
    ) -> list[RetrievalCandidate]:
        """Exercise explanations must never surface as evidence for an active,
        unanswered exercise (spec ss13/ss22): the tutor must help with the
        underlying concept, not reveal the correct option. This is enforced
        here, the single choke point every retrieval passes through, rather
        than trusted to every caller of `retrieve()`.
        """
        if context.context_type != TutorContextType.EXERCISE_HELP:
            return candidates
        if context.structured_context.get("exercise_submitted") is True:
            return candidates
        return [
            candidate
            for candidate in candidates
            if candidate.source.source_type != KnowledgeSourceType.CURRICULUM_EXERCISE_EXPLANATION
        ]
