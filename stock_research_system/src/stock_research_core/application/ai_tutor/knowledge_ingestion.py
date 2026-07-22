"""Turns published curriculum and approved local documents into
retrievable, embedded knowledge-base chunks.

Idempotent by construction: every document ID is deterministically
derived from `(logical identity, content hash)` via UUIDv5, so
re-ingesting unchanged content maps to the same document row (a no-op
after the first run) while changed content produces a new row - the
previous version is archived (`KnowledgeDocumentStatus.ARCHIVED`), never
deleted, per spec ss13's versioning requirement.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from stock_research_core.application.ai_tutor.models import (
    KnowledgeIngestionRunRecord,
    KnowledgeIngestionSummary,
)
from stock_research_core.application.ai_tutor.ports import EmbeddingPort, KnowledgeChunkerPort
from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.ai_tutor.enums import (
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeIngestionRunStatus,
    KnowledgeSourceType,
)
from stock_research_core.domain.ai_tutor.models import (
    KnowledgeChunkEmbedding,
    KnowledgeDocument,
    KnowledgeSource,
)
from stock_research_core.domain.learning.enums import LessonStatus
from stock_research_core.domain.learning.models import Exercise, Lesson
from stock_research_core.domain.models import utc_now
from stock_research_core.infrastructure.ai_tutor.local_document_parsers import (
    ParsedDocument,
    parse_local_document,
)

_NAMESPACE = uuid5(NAMESPACE_URL, "finquest.ai_tutor.knowledge_base")
_CURRICULUM_LESSON_SOURCE_ID = uuid5(_NAMESPACE, "source:curriculum-lessons")
_CURRICULUM_EXPLANATION_SOURCE_ID = uuid5(_NAMESPACE, "source:curriculum-exercise-explanations")
_CURRICULUM_PARSER_VERSION = "curriculum-ingestion-v1"

Clock = Callable[[], datetime]


class KnowledgeIngestionService:
    """Ingests FinQuest curriculum and approved local documents into the knowledge base."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], Any],
        chunker: KnowledgeChunkerPort,
        embedding_provider: EmbeddingPort,
        clock: Clock = utc_now,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._chunker = chunker
        self._embedding_provider = embedding_provider
        self._clock = clock

    # -- curriculum -----------------------------------------------

    async def ingest_curriculum(
        self, *, include_lessons: bool = True, include_exercise_explanations: bool = True
    ) -> KnowledgeIngestionSummary:
        counts = _Counts()
        async with self._unit_of_work_factory() as uow:
            run_record = await uow.knowledge.start_ingestion_run(
                source_id=None,
                document_id=None,
                chunking_version=self._chunker.chunking_version,
                embedding_model=self._embedding_provider.model_name,
                embedding_version=self._embedding_provider.embedding_version,
            )

            lesson_source: KnowledgeSource | None = None
            if include_lessons:
                lesson_source = await self._upsert_curriculum_source(
                    uow, _CURRICULUM_LESSON_SOURCE_ID, KnowledgeSourceType.CURRICULUM_LESSON,
                    "FinQuest Curriculum Lessons", counts,
                )
            explanation_source: KnowledgeSource | None = None
            if include_exercise_explanations:
                explanation_source = await self._upsert_curriculum_source(
                    uow, _CURRICULUM_EXPLANATION_SOURCE_ID, KnowledgeSourceType.CURRICULUM_EXERCISE_EXPLANATION,
                    "FinQuest Exercise Explanations", counts,
                )

            paths = await uow.curriculum.list_paths(published_only=True)
            for path in paths:
                modules = await uow.curriculum.list_modules(path.path_id)
                for module in modules:
                    lessons = await uow.curriculum.list_lessons(module.module_id)
                    for lesson in lessons:
                        if lesson.status != LessonStatus.PUBLISHED:
                            continue
                        if lesson_source is not None:
                            await self._ingest_lesson(uow, lesson_source, lesson, counts)
                        if explanation_source is not None:
                            exercises = await uow.curriculum.list_exercises(lesson.lesson_id)
                            for exercise in exercises:
                                if not exercise.active:
                                    continue
                                await self._ingest_exercise_explanation(
                                    uow, explanation_source, exercise, lesson, counts
                                )

            status = (
                KnowledgeIngestionRunStatus.COMPLETED
                if counts.documents_created or counts.documents_updated or counts.documents_skipped_unchanged
                else KnowledgeIngestionRunStatus.NO_CONTENT
            )
            completed_run = await uow.knowledge.complete_ingestion_run(
                run_record.run_id,
                status=status,
                documents_processed=counts.documents_processed,
                chunks_created=counts.chunks_created,
                embeddings_created=counts.embeddings_created,
            )
            await uow.commit()

        return counts.to_summary(completed_run)

    async def _upsert_curriculum_source(
        self, uow: Any, source_id: UUID, source_type: KnowledgeSourceType, title: str, counts: _Counts
    ) -> KnowledgeSource:
        existing = await uow.knowledge.get_source(source_id)
        source = KnowledgeSource(
            source_id=source_id,
            source_type=source_type,
            title=title,
            description="Approved FinQuest curriculum content, ingested directly from the published curriculum.",
            approval_status=KnowledgeApprovalStatus.APPROVED,
            trusted=True,
        )
        saved = await uow.knowledge.upsert_source(source)
        if existing is None:
            counts.sources_created += 1
        else:
            counts.sources_updated += 1
        return saved

    async def _ingest_lesson(self, uow: Any, source: KnowledgeSource, lesson: Lesson, counts: _Counts) -> None:
        skill_ids = list(dict.fromkeys([lesson.primary_skill_id, *lesson.secondary_skill_ids]))
        document = KnowledgeDocument(
            document_id=self._content_derived_id(f"lesson:{lesson.lesson_id}", lesson.content_markdown),
            source_id=source.source_id,
            title=lesson.title,
            content_text=lesson.content_markdown,
            content_hash=_sha256_hex(lesson.content_markdown),
            status=KnowledgeDocumentStatus.PROCESSED,
            approval_status=KnowledgeApprovalStatus.APPROVED,
            available_at=lesson.created_at,
            lesson_id=lesson.lesson_id,
            skill_ids=skill_ids,
            document_version="v1",
            parser_version=_CURRICULUM_PARSER_VERSION,
        )
        await self._upsert_document_if_new(
            uow, document, lesson_id=lesson.lesson_id, source_id=source.source_id, counts=counts
        )
        counts.documents_processed += 1

    async def _ingest_exercise_explanation(
        self, uow: Any, source: KnowledgeSource, exercise: Exercise, lesson: Lesson, counts: _Counts
    ) -> None:
        if not exercise.explanation.strip():
            return
        document = KnowledgeDocument(
            document_id=self._content_derived_id(
                f"exercise_explanation:{exercise.exercise_id}", exercise.explanation
            ),
            source_id=source.source_id,
            title=f"Explanation: {exercise.prompt[:200]}",
            content_text=exercise.explanation,
            content_hash=_sha256_hex(exercise.explanation),
            status=KnowledgeDocumentStatus.PROCESSED,
            approval_status=KnowledgeApprovalStatus.APPROVED,
            available_at=exercise.created_at,
            lesson_id=lesson.lesson_id,
            exercise_id=exercise.exercise_id,
            skill_ids=list(exercise.skill_ids),
            document_version="v1",
            parser_version=_CURRICULUM_PARSER_VERSION,
        )
        await self._upsert_document_if_new(
            uow, document, exercise_id=exercise.exercise_id, source_id=source.source_id, counts=counts
        )
        counts.documents_processed += 1

    # -- local documents -----------------------------------------------

    async def ingest_local_document(
        self,
        *,
        file_path: Path,
        source_title: str,
        approval_status: KnowledgeApprovalStatus,
        skill_ids: list[UUID],
        available_at: datetime,
    ) -> KnowledgeIngestionSummary:
        parsed = parse_local_document(file_path)
        counts = _Counts()

        async with self._unit_of_work_factory() as uow:
            source_id = uuid5(_NAMESPACE, f"source:local:{source_title}")
            existing_source = await uow.knowledge.get_source(source_id)
            source = KnowledgeSource(
                source_id=source_id,
                source_type=parsed.source_type,
                title=source_title,
                approval_status=approval_status,
                trusted=False,
            )
            saved_source = await uow.knowledge.upsert_source(source)
            if existing_source is None:
                counts.sources_created += 1
            else:
                counts.sources_updated += 1

            run_record = await uow.knowledge.start_ingestion_run(
                source_id=saved_source.source_id,
                document_id=None,
                chunking_version=self._chunker.chunking_version,
                embedding_model=self._embedding_provider.model_name,
                embedding_version=self._embedding_provider.embedding_version,
            )

            document = KnowledgeDocument(
                document_id=self._content_derived_id(f"local:{source_title}", parsed.text),
                source_id=saved_source.source_id,
                title=parsed.title or source_title,
                content_text=parsed.text,
                content_hash=parsed.content_hash,
                status=KnowledgeDocumentStatus.PROCESSED,
                approval_status=approval_status,
                available_at=available_at,
                skill_ids=list(dict.fromkeys(skill_ids)),
                document_version="v1",
                parser_version=f"local-document-parser-v1:{parsed.source_type.value}",
            )
            await self._upsert_document_if_new(uow, document, source_id=saved_source.source_id, counts=counts)
            counts.documents_processed += 1

            status = (
                KnowledgeIngestionRunStatus.COMPLETED if counts.documents_created else KnowledgeIngestionRunStatus.NO_CONTENT
            )
            completed_run = await uow.knowledge.complete_ingestion_run(
                run_record.run_id,
                status=status,
                documents_processed=counts.documents_processed,
                chunks_created=counts.chunks_created,
                embeddings_created=counts.embeddings_created,
            )
            await uow.commit()

        return counts.to_summary(completed_run)

    # -- re-embedding -----------------------------------------------

    async def reembed_document(self, document_id: UUID) -> KnowledgeIngestionSummary:
        """Re-embed a document's existing chunks with the currently configured
        embedding provider, without rewriting the source document or re-chunking.
        """
        counts = _Counts()
        async with self._unit_of_work_factory() as uow:
            document = await uow.knowledge.get_document(document_id)
            if document is None:
                raise PersistenceError(f"No knowledge document found with id '{document_id}'.")

            run_record = await uow.knowledge.start_ingestion_run(
                source_id=document.source_id,
                document_id=document.document_id,
                chunking_version=self._chunker.chunking_version,
                embedding_model=self._embedding_provider.model_name,
                embedding_version=self._embedding_provider.embedding_version,
            )

            chunks = await uow.knowledge.list_chunks_for_document(document_id)
            if chunks:
                vectors = await self._embedding_provider.embed_texts([chunk.content for chunk in chunks])
                embeddings = [
                    KnowledgeChunkEmbedding(
                        chunk_id=chunk.chunk_id,
                        embedding_model=self._embedding_provider.model_name,
                        embedding_version=self._embedding_provider.embedding_version,
                        embedding_dimension=len(vector),
                    )
                    for chunk, vector in zip(chunks, vectors)
                ]
                await uow.knowledge.upsert_embeddings(embeddings, vectors)
                counts.embeddings_created += len(embeddings)
            counts.documents_processed = 1

            completed_run = await uow.knowledge.complete_ingestion_run(
                run_record.run_id,
                status=KnowledgeIngestionRunStatus.COMPLETED,
                documents_processed=counts.documents_processed,
                chunks_created=0,
                embeddings_created=counts.embeddings_created,
            )
            await uow.commit()

        return counts.to_summary(completed_run)

    # -- shared helpers -----------------------------------------------

    async def _upsert_document_if_new(
        self, uow: Any, document: KnowledgeDocument, *, counts: _Counts, **superseded_filter: Any
    ) -> None:
        existing = await uow.knowledge.get_document(document.document_id)
        if existing is not None:
            counts.documents_skipped_unchanged += 1
            return

        saved = await uow.knowledge.upsert_document(document)
        counts.documents_created += 1

        chunks = self._chunker.chunk(document=saved, chunking_version=self._chunker.chunking_version)
        saved_chunks = await uow.knowledge.upsert_chunks(chunks)
        counts.chunks_created += len(saved_chunks)

        if saved_chunks:
            vectors = await self._embedding_provider.embed_texts([chunk.content for chunk in saved_chunks])
            embeddings = [
                KnowledgeChunkEmbedding(
                    chunk_id=chunk.chunk_id,
                    embedding_model=self._embedding_provider.model_name,
                    embedding_version=self._embedding_provider.embedding_version,
                    embedding_dimension=len(vector),
                )
                for chunk, vector in zip(saved_chunks, vectors)
            ]
            await uow.knowledge.upsert_embeddings(embeddings, vectors)
            counts.embeddings_created += len(embeddings)

        await self._archive_superseded_versions(uow, saved, counts, **superseded_filter)

    async def _archive_superseded_versions(
        self,
        uow: Any,
        current: KnowledgeDocument,
        counts: _Counts,
        *,
        lesson_id: UUID | None = None,
        exercise_id: UUID | None = None,
        scenario_id: UUID | None = None,
        source_id: UUID | None = None,
    ) -> None:
        if lesson_id is None and exercise_id is None and scenario_id is None and source_id is None:
            return
        others = await uow.knowledge.list_approved_documents(
            lesson_id=lesson_id, exercise_id=exercise_id, scenario_id=scenario_id, source_id=source_id
        )
        for other in others:
            if other.document_id == current.document_id:
                continue
            await uow.knowledge.archive_document(other.document_id)
            counts.documents_archived += 1

    @staticmethod
    def _content_derived_id(logical_key: str, content: str) -> UUID:
        return uuid5(_NAMESPACE, f"{logical_key}:{_sha256_hex(content)}")


def _sha256_hex(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _Counts:
    """Mutable running totals for one ingestion call - not a domain/application model."""

    def __init__(self) -> None:
        self.sources_created = 0
        self.sources_updated = 0
        self.documents_created = 0
        self.documents_updated = 0
        self.documents_archived = 0
        self.documents_skipped_unchanged = 0
        self.documents_processed = 0
        self.chunks_created = 0
        self.embeddings_created = 0

    def to_summary(self, run: KnowledgeIngestionRunRecord) -> KnowledgeIngestionSummary:
        return KnowledgeIngestionSummary(
            run=run,
            sources_created=self.sources_created,
            sources_updated=self.sources_updated,
            documents_created=self.documents_created,
            documents_updated=self.documents_updated,
            documents_archived=self.documents_archived,
            documents_skipped_unchanged=self.documents_skipped_unchanged,
            chunks_created=self.chunks_created,
            embeddings_created=self.embeddings_created,
        )
