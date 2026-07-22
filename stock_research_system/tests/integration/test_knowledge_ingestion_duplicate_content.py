"""PostgreSQL integration tests reproducing and fixing the Phase 10
stabilization bug: two different lessons with byte-identical
`content_markdown` used to violate `uq_knowledge_documents_hash_version`
(scoped only to `content_hash, document_version`) when both were
ingested via `KnowledgeIngestionService.ingest_curriculum()`.

Migration `0008_kb_doc_context_uniqueness` replaces that constraint
with one additionally scoped on `source_id`, `lesson_id`, `exercise_id`,
`scenario_id`, `portfolio_context_code` (NULLS NOT DISTINCT), so two
different lessons sharing identical text now both ingest successfully
and remain independently retrievable, while true re-ingestion of
unchanged content for the *same* lesson stays idempotent.
"""

from __future__ import annotations

import uuid

import pytest

from stock_research_core.application.ai_tutor.chunking import HeadingAwareWordChunker
from stock_research_core.application.ai_tutor.knowledge_ingestion import KnowledgeIngestionService
from stock_research_core.domain.ai_tutor.enums import KnowledgeIngestionRunStatus
from stock_research_core.domain.learning.enums import DifficultyLevel, FinancialSkillCategory, LessonStatus
from stock_research_core.domain.learning.models import Lesson, LearningModule, LearningPath, Skill
from stock_research_core.infrastructure.ai_tutor.deterministic_fake_embeddings import (
    DeterministicFakeEmbeddingAdapter,
)

pytestmark = pytest.mark.integration

_SHARED_CONTENT = "# Shared Lesson Content\n\nThis exact text is intentionally reused across two different lessons."


def _ingestion_service(uow_factory) -> KnowledgeIngestionService:
    return KnowledgeIngestionService(
        unit_of_work_factory=uow_factory, chunker=HeadingAwareWordChunker(),
        embedding_provider=DeterministicFakeEmbeddingAdapter(),
    )


async def _seed_two_lessons_with_identical_content(uow_factory) -> dict:
    """Two different, published lessons under two different modules/paths,
    both with `content_markdown == _SHARED_CONTENT` - the exact
    reproduction scenario described in the stabilization requirements."""
    suffix = uuid.uuid4().hex[:8].upper()
    async with uow_factory() as uow:
        skill = await uow.curriculum.upsert_skill(
            Skill(
                code=f"DUP_CONTENT_{suffix}", name="Skill", description="d",
                category=FinancialSkillCategory.MONEY_BASICS, difficulty=DifficultyLevel.BEGINNER,
            )
        )
        path = await uow.curriculum.upsert_path(
            LearningPath(
                code=f"dup-path-{suffix}", title="Path", description="d", difficulty=DifficultyLevel.BEGINNER,
                position=0, estimated_minutes=10, published=True,
            )
        )
        module = await uow.curriculum.upsert_module(
            LearningModule(
                path_id=path.path_id, code="mod", title="Module", description="d", position=0,
                estimated_minutes=10, published=True,
            )
        )
        lesson_a = await uow.curriculum.upsert_lesson(
            Lesson(
                module_id=module.module_id, code="lesson-a", title="Lesson A", summary="s",
                content_markdown=_SHARED_CONTENT, difficulty=DifficultyLevel.BEGINNER,
                status=LessonStatus.PUBLISHED, position=0, estimated_minutes=10,
                primary_skill_id=skill.skill_id,
            )
        )
        lesson_b = await uow.curriculum.upsert_lesson(
            Lesson(
                module_id=module.module_id, code="lesson-b", title="Lesson B", summary="s",
                content_markdown=_SHARED_CONTENT, difficulty=DifficultyLevel.BEGINNER,
                status=LessonStatus.PUBLISHED, position=1, estimated_minutes=10,
                primary_skill_id=skill.skill_id,
            )
        )
        await uow.commit()
    return {"lesson_a_id": lesson_a.lesson_id, "lesson_b_id": lesson_b.lesson_id}


async def test_two_lessons_with_identical_text_both_ingest_successfully(uow_factory) -> None:
    world = await _seed_two_lessons_with_identical_content(uow_factory)
    service = _ingestion_service(uow_factory)

    summary = await service.ingest_curriculum(include_exercise_explanations=False)

    assert summary.run.status in (KnowledgeIngestionRunStatus.COMPLETED,)
    assert summary.documents_created >= 2  # neither lesson was silently discarded

    async with uow_factory() as uow:
        doc_a = await uow.knowledge.list_approved_documents(lesson_id=world["lesson_a_id"])
        doc_b = await uow.knowledge.list_approved_documents(lesson_id=world["lesson_b_id"])

    assert len(doc_a) == 1
    assert len(doc_b) == 1
    assert doc_a[0].document_id != doc_b[0].document_id  # two distinct, independently retrievable documents
    assert doc_a[0].content_hash == doc_b[0].content_hash  # confirms the reproduction: identical content
    assert doc_a[0].lesson_id == world["lesson_a_id"]
    assert doc_b[0].lesson_id == world["lesson_b_id"]


async def test_reingesting_unchanged_content_for_the_same_lesson_is_idempotent(uow_factory) -> None:
    world = await _seed_two_lessons_with_identical_content(uow_factory)
    service = _ingestion_service(uow_factory)

    first_summary = await service.ingest_curriculum(include_exercise_explanations=False)
    assert first_summary.documents_created >= 2

    second_summary = await service.ingest_curriculum(include_exercise_explanations=False)
    assert second_summary.documents_created == 0
    assert second_summary.documents_skipped_unchanged >= 2  # same lesson, same text -> no-op, not a new row

    async with uow_factory() as uow:
        doc_a = await uow.knowledge.list_approved_documents(lesson_id=world["lesson_a_id"])
        doc_b = await uow.knowledge.list_approved_documents(lesson_id=world["lesson_b_id"])
    assert len(doc_a) == 1
    assert len(doc_b) == 1


async def test_changed_content_for_the_same_lesson_archives_the_old_version(uow_factory) -> None:
    world = await _seed_two_lessons_with_identical_content(uow_factory)
    service = _ingestion_service(uow_factory)
    await service.ingest_curriculum(include_exercise_explanations=False)

    async with uow_factory() as uow:
        lesson_a = await uow.curriculum.get_lesson(world["lesson_a_id"])
        updated_lesson_a = lesson_a.model_copy(update={"content_markdown": _SHARED_CONTENT + "\n\nUpdated."})
        await uow.curriculum.upsert_lesson(updated_lesson_a)
        await uow.commit()

    summary = await service.ingest_curriculum(include_exercise_explanations=False)
    assert summary.documents_created >= 1
    assert summary.documents_archived >= 1

    async with uow_factory() as uow:
        current_docs = await uow.knowledge.list_approved_documents(lesson_id=world["lesson_a_id"])
    assert len(current_docs) == 1
    assert "Updated." in current_docs[0].content_text


async def test_repository_level_reproduction_two_documents_same_hash_different_lesson(uow_factory) -> None:
    """The minimal reproduction at the repository layer, independent of
    the ingestion service's own ID-derivation logic - two documents that
    share `(content_hash, document_version, source_id)` but differ only
    by `lesson_id` must both persist without a constraint violation."""
    import hashlib

    from stock_research_core.domain.ai_tutor.enums import (
        KnowledgeApprovalStatus,
        KnowledgeDocumentStatus,
        KnowledgeSourceType,
    )
    from stock_research_core.domain.ai_tutor.models import KnowledgeDocument, KnowledgeSource
    from stock_research_core.domain.models import utc_now

    content = "Byte-identical repository-level reproduction text."
    content_hash = hashlib.sha256(content.encode()).hexdigest()

    async with uow_factory() as uow:
        skill = await uow.curriculum.upsert_skill(
            Skill(
                code=f"REPRO_{uuid.uuid4().hex[:8].upper()}", name="Skill", description="d",
                category=FinancialSkillCategory.MONEY_BASICS, difficulty=DifficultyLevel.BEGINNER,
            )
        )
        path = await uow.curriculum.upsert_path(
            LearningPath(
                code=f"repro-path-{uuid.uuid4().hex[:8]}", title="Path", description="d",
                difficulty=DifficultyLevel.BEGINNER, position=0, estimated_minutes=10, published=True,
            )
        )
        module = await uow.curriculum.upsert_module(
            LearningModule(
                path_id=path.path_id, code="mod", title="Module", description="d", position=0,
                estimated_minutes=10, published=True,
            )
        )
        lesson_x = await uow.curriculum.upsert_lesson(
            Lesson(
                module_id=module.module_id, code="x", title="X", summary="s", content_markdown="x",
                difficulty=DifficultyLevel.BEGINNER, status=LessonStatus.PUBLISHED, position=0,
                estimated_minutes=10, primary_skill_id=skill.skill_id,
            )
        )
        lesson_y = await uow.curriculum.upsert_lesson(
            Lesson(
                module_id=module.module_id, code="y", title="Y", summary="s", content_markdown="y",
                difficulty=DifficultyLevel.BEGINNER, status=LessonStatus.PUBLISHED, position=1,
                estimated_minutes=10, primary_skill_id=skill.skill_id,
            )
        )

        source = await uow.knowledge.upsert_source(
            KnowledgeSource(
                source_type=KnowledgeSourceType.CURRICULUM_LESSON, title="Repro Source",
                approval_status=KnowledgeApprovalStatus.APPROVED, trusted=True,
            )
        )

        doc_x = await uow.knowledge.upsert_document(
            KnowledgeDocument(
                source_id=source.source_id, title="Doc X", content_text=content, content_hash=content_hash,
                status=KnowledgeDocumentStatus.PROCESSED, approval_status=KnowledgeApprovalStatus.APPROVED,
                available_at=utc_now(), lesson_id=lesson_x.lesson_id, document_version="v1", parser_version="v1",
            )
        )
        # This second insert is exactly what previously raised UniqueViolationError.
        doc_y = await uow.knowledge.upsert_document(
            KnowledgeDocument(
                source_id=source.source_id, title="Doc Y", content_text=content, content_hash=content_hash,
                status=KnowledgeDocumentStatus.PROCESSED, approval_status=KnowledgeApprovalStatus.APPROVED,
                available_at=utc_now(), lesson_id=lesson_y.lesson_id, document_version="v1", parser_version="v1",
            )
        )
        await uow.commit()

    assert doc_x.document_id != doc_y.document_id
    assert doc_x.content_hash == doc_y.content_hash == content_hash
