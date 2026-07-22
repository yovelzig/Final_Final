"""Unit tests for `HybridKnowledgeRetriever`'s pure logic: the
exercise-answer leakage guard (spec ss13/ss22 - exercise explanations
must never surface for an active, unanswered exercise).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from stock_research_core.application.ai_tutor.models import RetrievalCandidate, TutorContext
from stock_research_core.application.ai_tutor.retrieval import HybridKnowledgeRetriever
from stock_research_core.domain.ai_tutor.enums import (
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeSourceType,
    TutorContextType,
)
from stock_research_core.domain.ai_tutor.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_HASH = hashlib.sha256(b"x").hexdigest()


def _candidate(source_type: KnowledgeSourceType, content: str = "content") -> RetrievalCandidate:
    source = KnowledgeSource(source_type=source_type, title="Source", approval_status=KnowledgeApprovalStatus.APPROVED)
    document = KnowledgeDocument(
        source_id=source.source_id, title="Doc", content_text=content, content_hash=_HASH,
        status=KnowledgeDocumentStatus.PROCESSED, approval_status=KnowledgeApprovalStatus.APPROVED,
        available_at=NOW, parser_version="v1",
    )
    chunk = KnowledgeChunk(
        document_id=document.document_id, chunk_index=0, content=content, content_hash=_HASH,
        word_count=1, estimated_token_count=1, available_at=NOW, chunking_version="heading-word-chunker-v1",
    )
    return RetrievalCandidate(chunk=chunk, source=source, document=document, metadata_score=0.5, combined_score=0.5)


class TestExerciseAnswerLeakageGuard:
    def test_filters_exercise_explanation_for_unanswered_exercise(self) -> None:
        candidates = [
            _candidate(KnowledgeSourceType.CURRICULUM_EXERCISE_EXPLANATION),
            _candidate(KnowledgeSourceType.CURRICULUM_LESSON),
        ]
        context = TutorContext(
            context_type=TutorContextType.EXERCISE_HELP, learner_id=uuid4(), exercise_id=uuid4()
        )
        filtered = HybridKnowledgeRetriever._apply_exercise_answer_leakage_guard(candidates, context)
        assert len(filtered) == 1
        assert filtered[0].source.source_type == KnowledgeSourceType.CURRICULUM_LESSON

    def test_allows_exercise_explanation_after_submission(self) -> None:
        candidates = [_candidate(KnowledgeSourceType.CURRICULUM_EXERCISE_EXPLANATION)]
        context = TutorContext(
            context_type=TutorContextType.EXERCISE_HELP, learner_id=uuid4(), exercise_id=uuid4(),
            structured_context={"exercise_submitted": True},
        )
        filtered = HybridKnowledgeRetriever._apply_exercise_answer_leakage_guard(candidates, context)
        assert len(filtered) == 1

    def test_non_exercise_context_is_unaffected(self) -> None:
        candidates = [_candidate(KnowledgeSourceType.CURRICULUM_EXERCISE_EXPLANATION)]
        context = TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=uuid4())
        filtered = HybridKnowledgeRetriever._apply_exercise_answer_leakage_guard(candidates, context)
        assert len(filtered) == 1

    def test_lesson_help_context_is_unaffected(self) -> None:
        candidates = [_candidate(KnowledgeSourceType.CURRICULUM_EXERCISE_EXPLANATION)]
        context = TutorContext(
            context_type=TutorContextType.LESSON_HELP, learner_id=uuid4(), lesson_id=uuid4()
        )
        filtered = HybridKnowledgeRetriever._apply_exercise_answer_leakage_guard(candidates, context)
        assert len(filtered) == 1

    def test_empty_candidates_returns_empty(self) -> None:
        context = TutorContext(
            context_type=TutorContextType.EXERCISE_HELP, learner_id=uuid4(), exercise_id=uuid4()
        )
        assert HybridKnowledgeRetriever._apply_exercise_answer_leakage_guard([], context) == []
