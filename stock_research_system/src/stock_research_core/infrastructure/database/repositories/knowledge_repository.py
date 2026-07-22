"""SQLAlchemy repository for the FinQuest knowledge base: sources,
documents, chunks, embeddings, hybrid retrieval, and ingestion-run audit
records.

Implements the reciprocal-rank-fusion hybrid search described in the
Phase 8 spec (ss14): a pgvector cosine-distance candidate pool, a
PostgreSQL full-text candidate pool (via the same `knowledge_chunk_tsvector`
SQL function the GIN index in migration `0006_grounded_ai_tutor` is
built on), and a deterministic metadata-relevance score, combined by
rank position (not raw score) and sorted by
`(combined_score desc, metadata_score desc, chunk_id asc)` for a fully
stable order. Raw embedding vectors are read here (inside
infrastructure) but never returned - only lineage crosses into
`RetrievalCandidate`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.ai_tutor.models import KnowledgeIngestionRunRecord, RetrievalCandidate
from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.ai_tutor.enums import (
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeIngestionRunStatus,
)
from stock_research_core.domain.ai_tutor.models import (
    KnowledgeChunk,
    KnowledgeChunkEmbedding,
    KnowledgeDocument,
    KnowledgeSource,
)
from stock_research_core.infrastructure.database.mappers.ai_tutor_mappers import (
    knowledge_chunk_embedding_orm_to_domain,
    knowledge_chunk_orm_to_domain,
    knowledge_document_orm_to_domain,
    knowledge_source_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.knowledge_chunk import KnowledgeChunkORM
from stock_research_core.infrastructure.database.orm.knowledge_chunk_embedding import (
    KnowledgeChunkEmbeddingORM,
)
from stock_research_core.infrastructure.database.orm.knowledge_document import (
    KnowledgeDocumentORM,
    KnowledgeDocumentSkillORM,
)
from stock_research_core.infrastructure.database.orm.knowledge_ingestion_run import KnowledgeIngestionRunORM
from stock_research_core.infrastructure.database.orm.knowledge_source import KnowledgeSourceORM

_METADATA_BASE_SCORE = 0.10
_METADATA_EXACT_MATCH_SCORE = 1.00
_METADATA_SKILL_MATCH_SCORE = 0.40
_METADATA_SKILL_MATCH_CAP = 1.00
_VECTOR_WEIGHT = 0.65
_LEXICAL_WEIGHT = 0.25
_METADATA_WEIGHT = 0.10
_RRF_K = 60


def _ingestion_run_to_record(row: KnowledgeIngestionRunORM) -> KnowledgeIngestionRunRecord:
    return KnowledgeIngestionRunRecord(
        run_id=row.run_id,
        source_id=row.source_id,
        document_id=row.document_id,
        status=KnowledgeIngestionRunStatus(row.status),
        documents_processed=row.documents_processed,
        chunks_created=row.chunks_created,
        embeddings_created=row.embeddings_created,
        chunking_version=row.chunking_version,
        embedding_model=row.embedding_model,
        embedding_version=row.embedding_version,
        started_at=row.started_at,
        completed_at=row.completed_at,
        error_type=row.error_type,
        error_message=row.error_message,
    )


class SqlAlchemyKnowledgeRepository:
    """Persists and queries knowledge sources, documents, chunks, and embeddings."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- sources -----------------------------------------------

    async def upsert_source(self, source: KnowledgeSource) -> KnowledgeSource:
        insert_stmt = pg_insert(KnowledgeSourceORM).values(
            source_id=source.source_id,
            source_type=source.source_type.value,
            title=source.title,
            description=source.description,
            approval_status=source.approval_status.value,
            canonical_url=source.canonical_url,
            publisher=source.publisher,
            license_note=source.license_note,
            default_language=source.default_language,
            trusted=source.trusted,
        )
        statement = insert_stmt.on_conflict_do_update(
            index_elements=["source_id"],
            set_={
                "source_type": insert_stmt.excluded.source_type,
                "title": insert_stmt.excluded.title,
                "description": insert_stmt.excluded.description,
                "approval_status": insert_stmt.excluded.approval_status,
                "canonical_url": insert_stmt.excluded.canonical_url,
                "publisher": insert_stmt.excluded.publisher,
                "license_note": insert_stmt.excluded.license_note,
                "default_language": insert_stmt.excluded.default_language,
                "trusted": insert_stmt.excluded.trusted,
                "updated_at": func.now(),
            },
        )
        await self._session.execute(statement)
        await self._session.flush()
        row = await self._session.get(KnowledgeSourceORM, source.source_id)
        assert row is not None
        return knowledge_source_orm_to_domain(row)

    async def get_source(self, source_id: UUID) -> KnowledgeSource | None:
        row = await self._session.get(KnowledgeSourceORM, source_id)
        return knowledge_source_orm_to_domain(row) if row is not None else None

    # -- documents -----------------------------------------------

    async def upsert_document(self, document: KnowledgeDocument) -> KnowledgeDocument:
        insert_stmt = pg_insert(KnowledgeDocumentORM).values(
            document_id=document.document_id,
            source_id=document.source_id,
            title=document.title,
            content_text=document.content_text,
            content_hash=document.content_hash,
            language=document.language,
            status=document.status.value,
            approval_status=document.approval_status.value,
            published_at=document.published_at,
            available_at=document.available_at,
            effective_until=document.effective_until,
            lesson_id=document.lesson_id,
            exercise_id=document.exercise_id,
            scenario_id=document.scenario_id,
            portfolio_context_code=document.portfolio_context_code,
            document_version=document.document_version,
            parser_version=document.parser_version,
        )
        statement = insert_stmt.on_conflict_do_update(
            index_elements=["document_id"],
            set_={
                "title": insert_stmt.excluded.title,
                "content_text": insert_stmt.excluded.content_text,
                "content_hash": insert_stmt.excluded.content_hash,
                "language": insert_stmt.excluded.language,
                "status": insert_stmt.excluded.status,
                "approval_status": insert_stmt.excluded.approval_status,
                "published_at": insert_stmt.excluded.published_at,
                "available_at": insert_stmt.excluded.available_at,
                "effective_until": insert_stmt.excluded.effective_until,
                "portfolio_context_code": insert_stmt.excluded.portfolio_context_code,
                "document_version": insert_stmt.excluded.document_version,
                "parser_version": insert_stmt.excluded.parser_version,
                "updated_at": func.now(),
            },
        )
        await self._session.execute(statement)

        await self._session.execute(
            delete(KnowledgeDocumentSkillORM).where(KnowledgeDocumentSkillORM.document_id == document.document_id)
        )
        for skill_id in document.skill_ids:
            self._session.add(KnowledgeDocumentSkillORM(document_id=document.document_id, skill_id=skill_id))
        await self._session.flush()

        row = await self._session.get(KnowledgeDocumentORM, document.document_id)
        assert row is not None
        return knowledge_document_orm_to_domain(row, list(document.skill_ids))

    async def get_document(self, document_id: UUID) -> KnowledgeDocument | None:
        row = await self._session.get(KnowledgeDocumentORM, document_id)
        if row is None:
            return None
        skill_ids = await self._load_document_skill_ids(document_id)
        return knowledge_document_orm_to_domain(row, skill_ids)

    async def get_document_by_hash(self, *, source_id: UUID, content_hash: str) -> KnowledgeDocument | None:
        statement = select(KnowledgeDocumentORM).where(
            KnowledgeDocumentORM.source_id == source_id,
            KnowledgeDocumentORM.content_hash == content_hash,
            KnowledgeDocumentORM.status != KnowledgeDocumentStatus.ARCHIVED.value,
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        if row is None:
            return None
        skill_ids = await self._load_document_skill_ids(row.document_id)
        return knowledge_document_orm_to_domain(row, skill_ids)

    async def list_processed_document_ids(self, *, limit: int = 10_000) -> list[UUID]:
        statement = (
            select(KnowledgeDocumentORM.document_id)
            .where(KnowledgeDocumentORM.status == KnowledgeDocumentStatus.PROCESSED.value)
            .order_by(KnowledgeDocumentORM.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def list_approved_documents(
        self,
        *,
        language: str | None = None,
        lesson_id: UUID | None = None,
        exercise_id: UUID | None = None,
        scenario_id: UUID | None = None,
        source_id: UUID | None = None,
    ) -> list[KnowledgeDocument]:
        statement = select(KnowledgeDocumentORM).where(
            KnowledgeDocumentORM.approval_status == KnowledgeApprovalStatus.APPROVED.value,
            KnowledgeDocumentORM.status == KnowledgeDocumentStatus.PROCESSED.value,
        )
        if language is not None:
            statement = statement.where(KnowledgeDocumentORM.language == language)
        if lesson_id is not None:
            statement = statement.where(KnowledgeDocumentORM.lesson_id == lesson_id)
        if exercise_id is not None:
            statement = statement.where(KnowledgeDocumentORM.exercise_id == exercise_id)
        if scenario_id is not None:
            statement = statement.where(KnowledgeDocumentORM.scenario_id == scenario_id)
        if source_id is not None:
            statement = statement.where(KnowledgeDocumentORM.source_id == source_id)
        statement = statement.order_by(KnowledgeDocumentORM.created_at.asc())
        result = await self._session.execute(statement)
        documents = []
        for row in result.scalars().all():
            skill_ids = await self._load_document_skill_ids(row.document_id)
            documents.append(knowledge_document_orm_to_domain(row, skill_ids))
        return documents

    async def archive_document(self, document_id: UUID) -> KnowledgeDocument:
        row = await self._session.get(KnowledgeDocumentORM, document_id)
        if row is None:
            raise PersistenceError(f"No knowledge document found with id '{document_id}'.")
        row.status = KnowledgeDocumentStatus.ARCHIVED.value
        row.approval_status = KnowledgeApprovalStatus.ARCHIVED.value
        await self._session.flush()
        await self._session.refresh(row)
        skill_ids = await self._load_document_skill_ids(document_id)
        return knowledge_document_orm_to_domain(row, skill_ids)

    async def _load_document_skill_ids(self, document_id: UUID) -> list[UUID]:
        statement = select(KnowledgeDocumentSkillORM.skill_id).where(
            KnowledgeDocumentSkillORM.document_id == document_id
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    # -- chunks -----------------------------------------------

    async def upsert_chunks(self, chunks: list[KnowledgeChunk]) -> list[KnowledgeChunk]:
        results: list[KnowledgeChunk] = []
        for chunk in chunks:
            insert_stmt = pg_insert(KnowledgeChunkORM).values(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                heading_path=list(chunk.heading_path),
                content=chunk.content,
                content_hash=chunk.content_hash,
                word_count=chunk.word_count,
                estimated_token_count=chunk.estimated_token_count,
                available_at=chunk.available_at,
                effective_until=chunk.effective_until,
                chunking_version=chunk.chunking_version,
            )
            statement = insert_stmt.on_conflict_do_update(
                index_elements=["document_id", "chunk_index", "chunking_version"],
                set_={
                    "heading_path": insert_stmt.excluded.heading_path,
                    "content": insert_stmt.excluded.content,
                    "content_hash": insert_stmt.excluded.content_hash,
                    "word_count": insert_stmt.excluded.word_count,
                    "estimated_token_count": insert_stmt.excluded.estimated_token_count,
                    "available_at": insert_stmt.excluded.available_at,
                    "effective_until": insert_stmt.excluded.effective_until,
                    "updated_at": func.now(),
                },
            ).returning(KnowledgeChunkORM)
            result = await self._session.execute(statement)
            row = result.scalar_one()
            results.append(knowledge_chunk_orm_to_domain(row))
        await self._session.flush()
        return results

    async def list_chunks_for_document(self, document_id: UUID) -> list[KnowledgeChunk]:
        statement = (
            select(KnowledgeChunkORM)
            .where(KnowledgeChunkORM.document_id == document_id)
            .order_by(KnowledgeChunkORM.chunk_index.asc())
        )
        result = await self._session.execute(statement)
        return [knowledge_chunk_orm_to_domain(row) for row in result.scalars().all()]

    # -- embeddings -----------------------------------------------

    async def upsert_embeddings(
        self, embeddings: list[KnowledgeChunkEmbedding], vectors: list[list[float]]
    ) -> list[KnowledgeChunkEmbedding]:
        if len(embeddings) != len(vectors):
            raise PersistenceError("embeddings and vectors must have equal lengths")
        results: list[KnowledgeChunkEmbedding] = []
        for embedding, vector in zip(embeddings, vectors):
            insert_stmt = pg_insert(KnowledgeChunkEmbeddingORM).values(
                embedding_id=embedding.embedding_id,
                chunk_id=embedding.chunk_id,
                embedding_model=embedding.embedding_model,
                embedding_version=embedding.embedding_version,
                embedding_dimension=embedding.embedding_dimension,
                embedding=vector,
            )
            statement = insert_stmt.on_conflict_do_update(
                index_elements=["chunk_id", "embedding_model", "embedding_version"],
                set_={
                    "embedding_dimension": insert_stmt.excluded.embedding_dimension,
                    "embedding": insert_stmt.excluded.embedding,
                    "updated_at": func.now(),
                },
            ).returning(KnowledgeChunkEmbeddingORM)
            result = await self._session.execute(statement)
            row = result.scalar_one()
            results.append(knowledge_chunk_embedding_orm_to_domain(row))
        await self._session.flush()
        return results

    # -- retrieval -----------------------------------------------

    async def get_chunk_with_metadata(self, chunk_id: UUID) -> RetrievalCandidate | None:
        candidates = await self._load_candidates([chunk_id])
        candidate = candidates.get(chunk_id)
        if candidate is None:
            return None
        chunk, document, source = candidate
        return RetrievalCandidate(
            chunk=knowledge_chunk_orm_to_domain(chunk),
            source=knowledge_source_orm_to_domain(source),
            document=knowledge_document_orm_to_domain(document, await self._load_document_skill_ids(document.document_id)),
            vector_score=None,
            lexical_score=None,
            metadata_score=_METADATA_BASE_SCORE,
            combined_score=0.0,
        )

    async def hybrid_search(
        self,
        *,
        query_embedding: list[float] | None,
        embedding_model: str | None,
        embedding_version: str | None,
        lexical_query: str,
        top_k: int,
        candidate_pool_size: int = 40,
        approved_only: bool = True,
        language: str = "en",
        skill_ids: list[UUID] | None = None,
        lesson_id: UUID | None = None,
        exercise_id: UUID | None = None,
        scenario_id: UUID | None = None,
        portfolio_context_code: str | None = None,
        knowledge_cutoff_at: datetime | None = None,
    ) -> tuple[list[RetrievalCandidate], int]:
        base_conditions = [KnowledgeDocumentORM.language == language]
        if approved_only:
            base_conditions.append(KnowledgeSourceORM.approval_status == KnowledgeApprovalStatus.APPROVED.value)
            base_conditions.append(KnowledgeDocumentORM.approval_status == KnowledgeApprovalStatus.APPROVED.value)
            base_conditions.append(KnowledgeDocumentORM.status == KnowledgeDocumentStatus.PROCESSED.value)
        if knowledge_cutoff_at is not None:
            base_conditions.append(KnowledgeChunkORM.available_at <= knowledge_cutoff_at)
            base_conditions.append(
                or_(
                    KnowledgeChunkORM.effective_until.is_(None),
                    KnowledgeChunkORM.effective_until > knowledge_cutoff_at,
                )
            )

        vector_hits: dict[UUID, tuple[int, float]] = {}
        if query_embedding is not None and embedding_model is not None and embedding_version is not None:
            distance = KnowledgeChunkEmbeddingORM.embedding.cosine_distance(query_embedding)
            statement = (
                select(KnowledgeChunkORM.chunk_id, distance.label("distance"))
                .join(
                    KnowledgeChunkEmbeddingORM,
                    KnowledgeChunkEmbeddingORM.chunk_id == KnowledgeChunkORM.chunk_id,
                )
                .join(KnowledgeDocumentORM, KnowledgeDocumentORM.document_id == KnowledgeChunkORM.document_id)
                .join(KnowledgeSourceORM, KnowledgeSourceORM.source_id == KnowledgeDocumentORM.source_id)
                .where(
                    KnowledgeChunkEmbeddingORM.embedding_model == embedding_model,
                    KnowledgeChunkEmbeddingORM.embedding_version == embedding_version,
                    *base_conditions,
                )
                .order_by(distance.asc())
                .limit(candidate_pool_size)
            )
            result = await self._session.execute(statement)
            for rank, (chunk_id, dist) in enumerate(result.all(), start=1):
                vector_hits[chunk_id] = (rank, 1.0 - float(dist))

        lexical_hits: dict[UUID, tuple[int, float]] = {}
        if lexical_query.strip():
            tsvector = func.knowledge_chunk_tsvector(KnowledgeChunkORM.heading_path, KnowledgeChunkORM.content)
            tsquery = func.plainto_tsquery("english", lexical_query)
            rank_expr = func.ts_rank_cd(tsvector, tsquery)
            statement = (
                select(KnowledgeChunkORM.chunk_id, rank_expr.label("rank"))
                .join(KnowledgeDocumentORM, KnowledgeDocumentORM.document_id == KnowledgeChunkORM.document_id)
                .join(KnowledgeSourceORM, KnowledgeSourceORM.source_id == KnowledgeDocumentORM.source_id)
                .where(tsvector.op("@@")(tsquery), *base_conditions)
                .order_by(rank_expr.desc())
                .limit(candidate_pool_size)
            )
            result = await self._session.execute(statement)
            for rank, (chunk_id, score) in enumerate(result.all(), start=1):
                lexical_hits[chunk_id] = (rank, float(score))

        candidate_chunk_ids = set(vector_hits) | set(lexical_hits)
        if not candidate_chunk_ids:
            return [], 0

        loaded = await self._load_candidates(candidate_chunk_ids)
        skill_id_set = set(skill_ids or [])

        scored: list[tuple[float, float, str, RetrievalCandidate]] = []
        for chunk_id in candidate_chunk_ids:
            entry = loaded.get(chunk_id)
            if entry is None:
                continue
            chunk_row, document_row, source_row = entry
            document_skill_ids = await self._load_document_skill_ids(document_row.document_id)

            metadata_score = _METADATA_BASE_SCORE
            if lesson_id is not None and document_row.lesson_id == lesson_id:
                metadata_score += _METADATA_EXACT_MATCH_SCORE
            if exercise_id is not None and document_row.exercise_id == exercise_id:
                metadata_score += _METADATA_EXACT_MATCH_SCORE
            if scenario_id is not None and document_row.scenario_id == scenario_id:
                metadata_score += _METADATA_EXACT_MATCH_SCORE
            if portfolio_context_code is not None and document_row.portfolio_context_code == portfolio_context_code:
                metadata_score += _METADATA_EXACT_MATCH_SCORE
            matching_skills = len(skill_id_set & set(document_skill_ids))
            if matching_skills:
                metadata_score += min(
                    _METADATA_SKILL_MATCH_SCORE * matching_skills, _METADATA_SKILL_MATCH_CAP
                )
            metadata_score = min(metadata_score, 1.0)

            vector_rank, vector_score = vector_hits.get(chunk_id, (None, None))
            lexical_rank, lexical_score = lexical_hits.get(chunk_id, (None, None))
            vector_component = _VECTOR_WEIGHT / (_RRF_K + vector_rank) if vector_rank is not None else 0.0
            lexical_component = _LEXICAL_WEIGHT / (_RRF_K + lexical_rank) if lexical_rank is not None else 0.0
            combined_score = vector_component + lexical_component + (_METADATA_WEIGHT * metadata_score)

            candidate = RetrievalCandidate(
                chunk=knowledge_chunk_orm_to_domain(chunk_row),
                source=knowledge_source_orm_to_domain(source_row),
                document=knowledge_document_orm_to_domain(document_row, document_skill_ids),
                vector_score=vector_score,
                lexical_score=lexical_score,
                metadata_score=metadata_score,
                combined_score=combined_score,
            )
            scored.append((-combined_score, -metadata_score, str(chunk_id), candidate))

        scored.sort(key=lambda item: (item[0], item[1], item[2]))
        top_candidates = [item[3] for item in scored[:top_k]]
        return top_candidates, len(candidate_chunk_ids)

    async def _load_candidates(
        self, chunk_ids: set[UUID] | list[UUID]
    ) -> dict[UUID, tuple[KnowledgeChunkORM, KnowledgeDocumentORM, KnowledgeSourceORM]]:
        if not chunk_ids:
            return {}
        statement = (
            select(KnowledgeChunkORM, KnowledgeDocumentORM, KnowledgeSourceORM)
            .join(KnowledgeDocumentORM, KnowledgeDocumentORM.document_id == KnowledgeChunkORM.document_id)
            .join(KnowledgeSourceORM, KnowledgeSourceORM.source_id == KnowledgeDocumentORM.source_id)
            .where(KnowledgeChunkORM.chunk_id.in_(list(chunk_ids)))
        )
        result = await self._session.execute(statement)
        return {chunk.chunk_id: (chunk, document, source) for chunk, document, source in result.all()}

    # -- ingestion runs -----------------------------------------------

    async def start_ingestion_run(
        self,
        *,
        source_id: UUID | None,
        document_id: UUID | None,
        chunking_version: str,
        embedding_model: str,
        embedding_version: str,
    ) -> KnowledgeIngestionRunRecord:
        row = KnowledgeIngestionRunORM(
            run_id=uuid4(),
            source_id=source_id,
            document_id=document_id,
            status=KnowledgeIngestionRunStatus.STARTED.value,
            chunking_version=chunking_version,
            embedding_model=embedding_model,
            embedding_version=embedding_version,
            started_at=func.now(),
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return _ingestion_run_to_record(row)

    async def complete_ingestion_run(
        self,
        run_id: UUID,
        *,
        status: KnowledgeIngestionRunStatus,
        documents_processed: int = 0,
        chunks_created: int = 0,
        embeddings_created: int = 0,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> KnowledgeIngestionRunRecord:
        row = await self._session.get(KnowledgeIngestionRunORM, run_id)
        if row is None:
            raise PersistenceError(f"No knowledge ingestion run found with id '{run_id}'.")
        row.status = status.value
        row.documents_processed = documents_processed
        row.chunks_created = chunks_created
        row.embeddings_created = embeddings_created
        row.error_type = error_type
        row.error_message = error_message
        row.completed_at = datetime.now(timezone.utc)
        await self._session.flush()
        await self._session.refresh(row)
        return _ingestion_run_to_record(row)

    async def list_recent_ingestion_runs(self, limit: int = 10) -> list[KnowledgeIngestionRunRecord]:
        statement = (
            select(KnowledgeIngestionRunORM).order_by(KnowledgeIngestionRunORM.started_at.desc()).limit(limit)
        )
        result = await self._session.execute(statement)
        return [_ingestion_run_to_record(row) for row in result.scalars().all()]

    # -- counts -----------------------------------------------

    async def count_sources(self) -> int:
        result = await self._session.execute(select(func.count()).select_from(KnowledgeSourceORM))
        return int(result.scalar_one())

    async def count_approved_documents(self) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(KnowledgeDocumentORM)
            .where(KnowledgeDocumentORM.approval_status == KnowledgeApprovalStatus.APPROVED.value)
        )
        return int(result.scalar_one())

    async def count_chunks(self) -> int:
        result = await self._session.execute(select(func.count()).select_from(KnowledgeChunkORM))
        return int(result.scalar_one())

    async def count_embeddings(self) -> int:
        result = await self._session.execute(select(func.count()).select_from(KnowledgeChunkEmbeddingORM))
        return int(result.scalar_one())
