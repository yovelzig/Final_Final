"""SQLAlchemy repository for `TutorRetrievalRun` audit persistence.

`returned_chunk_ids`/`returned_scores` live in the
`tutor_retrieval_run_chunks` association table, ordered by `rank` -
the same "replace association rows wholesale" idiom used throughout
this codebase (e.g. `SqlAlchemyMarketScenarioRepository`).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.ai_tutor.models import RetrievalCandidate
from stock_research_core.domain.ai_tutor.models import TutorRetrievalRun
from stock_research_core.infrastructure.database.mappers.ai_tutor_mappers import (
    tutor_retrieval_run_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.tutor_retrieval_run import (
    TutorRetrievalRunChunkORM,
    TutorRetrievalRunORM,
)


class SqlAlchemyRetrievalAuditRepository:
    """Persists and queries retrieval-run audit records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_run(
        self, run: TutorRetrievalRun, candidates: list[RetrievalCandidate]
    ) -> TutorRetrievalRun:
        row = TutorRetrievalRunORM(
            retrieval_run_id=run.retrieval_run_id,
            conversation_id=run.conversation_id,
            query_text=run.query_text,
            method=run.method.value,
            top_k=run.top_k,
            knowledge_cutoff_at=run.knowledge_cutoff_at,
            retrieval_policy_version=run.retrieval_policy_version,
            embedding_model=run.embedding_model,
            embedding_version=run.embedding_version,
            candidate_count=run.candidate_count,
        )
        self._session.add(row)
        # Flushed separately from the child rows below: `TutorRetrievalRunORM`
        # and `TutorRetrievalRunChunkORM` have no ORM `relationship()` between
        # them (plain FK columns only), so SQLAlchemy's flush-ordering
        # dependency sort - which is derived from `relationship()`s, not raw
        # FK constraints - has no way to know the parent must insert first.
        # The same pitfall, and the same fix (flush the parent immediately),
        # is documented in `SqlAlchemyMarketScenarioRepository.upsert`.
        await self._session.flush()
        for rank, (chunk_id, score) in enumerate(zip(run.returned_chunk_ids, run.returned_scores)):
            self._session.add(
                TutorRetrievalRunChunkORM(
                    retrieval_run_id=run.retrieval_run_id, rank=rank, chunk_id=chunk_id, score=score
                )
            )
        await self._session.flush()
        return tutor_retrieval_run_orm_to_domain(row, list(run.returned_chunk_ids), list(run.returned_scores))

    async def get_run(self, retrieval_run_id: UUID) -> TutorRetrievalRun | None:
        row = await self._session.get(TutorRetrievalRunORM, retrieval_run_id)
        if row is None:
            return None
        chunk_ids, scores = await self._load_chunks(retrieval_run_id)
        return tutor_retrieval_run_orm_to_domain(row, chunk_ids, scores)

    async def list_recent_runs(self, conversation_id: UUID, limit: int = 10) -> list[TutorRetrievalRun]:
        statement = (
            select(TutorRetrievalRunORM)
            .where(TutorRetrievalRunORM.conversation_id == conversation_id)
            .order_by(desc(TutorRetrievalRunORM.created_at))
            .limit(limit)
        )
        result = await self._session.execute(statement)
        rows = result.scalars().all()
        runs = []
        for row in rows:
            chunk_ids, scores = await self._load_chunks(row.retrieval_run_id)
            runs.append(tutor_retrieval_run_orm_to_domain(row, chunk_ids, scores))
        return runs

    async def _load_chunks(self, retrieval_run_id: UUID) -> tuple[list[UUID], list[float]]:
        statement = (
            select(TutorRetrievalRunChunkORM.chunk_id, TutorRetrievalRunChunkORM.score)
            .where(TutorRetrievalRunChunkORM.retrieval_run_id == retrieval_run_id)
            .order_by(TutorRetrievalRunChunkORM.rank.asc())
        )
        result = await self._session.execute(statement)
        rows = result.all()
        return [row[0] for row in rows], [row[1] for row in rows]
