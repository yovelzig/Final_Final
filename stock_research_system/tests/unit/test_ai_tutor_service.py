"""Unit tests for `GroundedAITutorService`.

Uses fake in-memory repository implementations and a fake Unit of Work -
no SQLAlchemy or PostgreSQL is involved anywhere in this file. The real
`RuleBasedTutorGuardrail` and `GroundedTutorPromptBuilder` are used (not
further fakes) so these tests also exercise the guardrail/service
integration; retrieval and generation are faked so each test can
control exactly what evidence/answer text is available.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from stock_research_core.application.ai_tutor.guardrails import RuleBasedTutorGuardrail
from stock_research_core.application.ai_tutor.models import RetrievalCandidate, TutorContext, TutorModelResult
from stock_research_core.application.ai_tutor.prompt_builder import GroundedTutorPromptBuilder
from stock_research_core.application.ai_tutor.service import GroundedAITutorService
from stock_research_core.application.exceptions import (
    InactiveLearnerError,
    LearnerNotFoundError,
    TutorConversationNotActiveError,
    TutorConversationNotFoundError,
)
from stock_research_core.domain.ai_tutor.enums import (
    GroundingStatus,
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeSourceType,
    RetrievalMethod,
    TutorAnswerStatus,
    TutorContextType,
    TutorConversationStatus,
    TutorProviderType,
)
from stock_research_core.domain.ai_tutor.models import (
    EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    TutorRetrievalRun,
)
from stock_research_core.domain.learning.enums import DifficultyLevel
from stock_research_core.domain.learning.models import LearnerProfile

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_HASH = hashlib.sha256(b"x").hexdigest()

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeLearnerRepository:
    def __init__(self, store: dict) -> None:
        self._store = store

    async def get(self, learner_id: UUID):
        return self._store.get(learner_id)


class FakeConversationRepository:
    def __init__(self, conversations: dict, messages: dict) -> None:
        self._conversations = conversations
        self._messages = messages

    async def create_conversation(self, conversation):
        self._conversations[conversation.conversation_id] = conversation
        return conversation

    async def get_conversation(self, conversation_id: UUID):
        return self._conversations.get(conversation_id)

    async def list_active_conversations_for_learner(self, learner_id: UUID):
        return [
            c for c in self._conversations.values()
            if c.learner_id == learner_id and c.status == TutorConversationStatus.ACTIVE
        ]

    async def add_message(self, message):
        self._messages.setdefault(message.conversation_id, []).append(message)
        return message

    async def list_recent_messages(self, conversation_id: UUID, limit: int = 10):
        return self._messages.get(conversation_id, [])[-limit:]

    async def close_conversation(self, conversation_id: UUID, *, closed_at):
        conversation = self._conversations[conversation_id]
        updated = conversation.model_copy(update={"status": TutorConversationStatus.CLOSED, "closed_at": closed_at})
        self._conversations[conversation_id] = updated
        return updated


class FakeGuardrailRepository:
    def __init__(self, store: dict) -> None:
        self._store = store

    async def save_decision(self, decision):
        self._store[decision.decision_id] = decision
        return decision

    async def get_decision(self, decision_id: UUID):
        return self._store.get(decision_id)

    async def list_decisions_for_conversation(self, conversation_id: UUID):
        return [d for d in self._store.values() if d.conversation_id == conversation_id]


class FakeRetrievalAuditRepository:
    def __init__(self, store: dict) -> None:
        self._store = store

    async def save_run(self, run, candidates):
        self._store[run.retrieval_run_id] = run
        return run

    async def get_run(self, retrieval_run_id: UUID):
        return self._store.get(retrieval_run_id)

    async def list_recent_runs(self, conversation_id: UUID, limit: int = 10):
        return [r for r in self._store.values() if r.conversation_id == conversation_id][:limit]


class FakeTutorAnswerRepository:
    def __init__(self, answers: dict, citations: dict) -> None:
        self._answers = answers
        self._citations = citations

    async def save_answer(self, answer):
        self._answers[answer.answer_id] = answer
        return answer

    async def save_citations(self, citations):
        for citation in citations:
            self._citations.setdefault(citation.answer_id, []).append(citation)
        return citations

    async def get_answer(self, answer_id: UUID):
        return self._answers.get(answer_id)

    async def list_citations_for_answer(self, answer_id: UUID):
        return self._citations.get(answer_id, [])

    async def list_answers_for_conversation(self, conversation_id: UUID):
        return [a for a in self._answers.values() if a.conversation_id == conversation_id]

    async def update_validation_status(self, answer_id: UUID, *, status, grounding_status, validated_at):
        answer = self._answers[answer_id]
        updated = answer.model_copy(
            update={"status": status, "grounding_status": grounding_status, "validated_at": validated_at}
        )
        self._answers[answer_id] = updated
        return updated


class FakeKnowledgeGapRepository:
    def __init__(self, store: dict) -> None:
        self._store = store

    async def upsert_gap(self, gap):
        self._store[gap.gap_id] = gap
        return gap

    async def get_by_question_and_context(self, normalized_question: str, context_type: str):
        for gap in self._store.values():
            if gap.normalized_question == normalized_question and gap.context_type.value == context_type and not gap.resolved:
                return gap
        return None

    async def list_unresolved_gaps(self, limit: int = 50):
        return [g for g in self._store.values() if not g.resolved][:limit]

    async def resolve_gap(self, gap_id: UUID, *, resolved_at, resolution_document_id):
        gap = self._store[gap_id]
        updated = gap.model_copy(
            update={"resolved": True, "resolved_at": resolved_at, "resolution_document_id": resolution_document_id}
        )
        self._store[gap_id] = updated
        return updated

    async def count_repeated_gaps(self, minimum_occurrences: int = 2):
        return sum(1 for g in self._store.values() if g.occurrence_count >= minimum_occurrences and not g.resolved)


class FakeUnitOfWork:
    def __init__(self, store: dict) -> None:
        self._store = store

    async def __aenter__(self):
        self.learners = FakeLearnerRepository(self._store["learners"])
        self.tutor_conversations = FakeConversationRepository(self._store["conversations"], self._store["messages"])
        self.tutor_guardrails = FakeGuardrailRepository(self._store["guardrail_decisions"])
        self.tutor_retrieval = FakeRetrievalAuditRepository(self._store["retrieval_runs"])
        self.tutor_answers = FakeTutorAnswerRepository(self._store["answers"], self._store["citations"])
        self.tutor_knowledge_gaps = FakeKnowledgeGapRepository(self._store["knowledge_gaps"])
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def _make_uow_factory():
    store = {
        "learners": {}, "conversations": {}, "messages": {}, "guardrail_decisions": {},
        "retrieval_runs": {}, "answers": {}, "citations": {}, "knowledge_gaps": {},
    }
    return (lambda: FakeUnitOfWork(store)), store


def _candidate(content: str = "Diversification reduces reliance on a single asset.") -> RetrievalCandidate:
    source = KnowledgeSource(
        source_type=KnowledgeSourceType.LOCAL_MARKDOWN, title="Approved Source",
        approval_status=KnowledgeApprovalStatus.APPROVED,
    )
    document = KnowledgeDocument(
        source_id=source.source_id, title="Doc", content_text=content, content_hash=_HASH,
        status=KnowledgeDocumentStatus.PROCESSED, approval_status=KnowledgeApprovalStatus.APPROVED,
        available_at=NOW, parser_version="v1",
    )
    chunk = KnowledgeChunk(
        document_id=document.document_id, chunk_index=0, content=content, content_hash=_HASH,
        word_count=len(content.split()), estimated_token_count=len(content.split()) + 2,
        available_at=NOW, chunking_version="heading-word-chunker-v1",
    )
    return RetrievalCandidate(chunk=chunk, source=source, document=document, metadata_score=0.5, combined_score=0.5)


class FakeRetriever:
    def __init__(self, candidates: list[RetrievalCandidate] | None = None) -> None:
        self.candidates = candidates or []
        self.calls: list[str] = []

    async def retrieve(self, *, query: str, context: TutorContext, top_k: int = 8):
        self.calls.append(query)
        run = TutorRetrievalRun(
            conversation_id=UUID(int=0), query_text=query, method=RetrievalMethod.HYBRID, top_k=top_k,
            knowledge_cutoff_at=context.knowledge_cutoff_at, retrieval_policy_version="hybrid-retrieval-v1",
            embedding_model="fake", embedding_version="v1", candidate_count=len(self.candidates),
            returned_chunk_ids=[c.chunk.chunk_id for c in self.candidates],
            returned_scores=[c.combined_score for c in self.candidates],
        )
        return run, self.candidates


class FakeTutorModel:
    provider_type = TutorProviderType.EXTRACTIVE

    def __init__(self, result: TutorModelResult | None = None) -> None:
        self.result = result
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        if self.result is not None:
            return self.result
        candidate_ids = [c.chunk.chunk_id for c in request.retrieved_candidates]
        return TutorModelResult(
            answer_markdown="Diversification reduces reliance on a single asset [1].",
            cited_chunk_ids=candidate_ids[:1], provider_type=TutorProviderType.EXTRACTIVE,
            model_name="extractive-tutor-v1",
        )


def _build_service(uow_factory, *, candidates=None, model_result=None):
    retriever = FakeRetriever(candidates)
    tutor_model = FakeTutorModel(model_result)
    guardrail = RuleBasedTutorGuardrail()
    prompt_builder = GroundedTutorPromptBuilder()
    service = GroundedAITutorService(
        unit_of_work_factory=uow_factory, retriever=retriever, tutor_model=tutor_model,
        guardrail=guardrail, prompt_builder=prompt_builder, clock=lambda: NOW,
    )
    return service, retriever, tutor_model


def _learner() -> LearnerProfile:
    return LearnerProfile(learner_id=uuid4(), display_name="Test Learner", financial_experience_level=DifficultyLevel.BEGINNER)


@pytest.mark.asyncio
class TestCreateConversation:
    async def test_creates_conversation_for_active_learner(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        service, _r, _m = _build_service(uow_factory)

        context = TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=learner.learner_id)
        conversation = await service.create_conversation(learner_id=learner.learner_id, context=context)
        assert conversation.status == TutorConversationStatus.ACTIVE
        assert conversation.context_type == TutorContextType.GENERAL_EDUCATION

    async def test_unknown_learner_raises(self) -> None:
        uow_factory, _store = _make_uow_factory()
        service, _r, _m = _build_service(uow_factory)
        context = TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=uuid4())
        with pytest.raises(LearnerNotFoundError):
            await service.create_conversation(learner_id=uuid4(), context=context)

    async def test_inactive_learner_raises(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner().model_copy(update={"active": False})
        store["learners"][learner.learner_id] = learner
        service, _r, _m = _build_service(uow_factory)
        context = TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=learner.learner_id)
        with pytest.raises(InactiveLearnerError):
            await service.create_conversation(learner_id=learner.learner_id, context=context)


@pytest.mark.asyncio
class TestAsk:
    async def _create_conversation(self, service, learner, store):
        context = TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=learner.learner_id)
        return await service.create_conversation(learner_id=learner.learner_id, context=context)

    async def test_grounded_answer_with_citation(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        candidate = _candidate()
        service, retriever, tutor_model = _build_service(uow_factory, candidates=[candidate])
        conversation = await self._create_conversation(service, learner, store)

        response = await service.ask(conversation_id=conversation.conversation_id, question="What is diversification?")

        assert response.answer.status == TutorAnswerStatus.VALIDATED
        assert response.answer.grounding_status == GroundingStatus.GROUNDED
        assert len(response.citations) == 1
        assert response.citations[0].source_title == "Approved Source"
        assert retriever.calls == ["What is diversification?"]
        assert tutor_model.calls == 1

    async def test_buy_sell_request_refuses_without_retrieval(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        service, retriever, tutor_model = _build_service(uow_factory, candidates=[_candidate()])
        conversation = await self._create_conversation(service, learner, store)

        response = await service.ask(conversation_id=conversation.conversation_id, question="Should I buy NVDA?")

        assert response.answer.status == TutorAnswerStatus.REJECTED
        assert response.guardrail.action.value == "REFUSE"
        assert retriever.calls == []
        assert tutor_model.calls == 0
        assert response.citations == []

    async def test_off_topic_question_falls_back_and_logs_gap(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        service, retriever, _m = _build_service(uow_factory)
        conversation = await self._create_conversation(service, learner, store)

        response = await service.ask(
            conversation_id=conversation.conversation_id,
            question="Can you recommend a good pizza restaurant near me?",
        )

        assert response.answer.status == TutorAnswerStatus.FALLBACK
        assert response.answer.answer_markdown == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK
        assert retriever.calls == []
        assert len(store["knowledge_gaps"]) == 1

    async def test_empty_retrieval_results_in_fallback(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        service, retriever, tutor_model = _build_service(uow_factory, candidates=[])
        conversation = await self._create_conversation(service, learner, store)

        response = await service.ask(conversation_id=conversation.conversation_id, question="What is diversification?")

        assert response.answer.status == TutorAnswerStatus.FALLBACK
        assert response.answer.answer_markdown == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK
        assert retriever.calls == ["What is diversification?"]
        assert tutor_model.calls == 0
        assert len(store["knowledge_gaps"]) == 1

    async def test_allow_with_boundary_prepends_boundary_text(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        candidate = _candidate()
        service, _r, _m = _build_service(uow_factory, candidates=[candidate])
        conversation = await self._create_conversation(service, learner, store)

        response = await service.ask(
            conversation_id=conversation.conversation_id, question="How should I invest my $50,000?"
        )

        assert response.guardrail.action.value == "ALLOW_WITH_BOUNDARY"
        assert "I can explain the concepts" in response.answer.answer_markdown

    async def test_invalid_citation_from_model_falls_back(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        candidate = _candidate()
        bad_result = TutorModelResult(
            answer_markdown="Some claim [1].", cited_chunk_ids=[uuid4()],
            provider_type=TutorProviderType.EXTRACTIVE, model_name="extractive-tutor-v1",
        )
        service, _r, tutor_model = _build_service(uow_factory, candidates=[candidate], model_result=bad_result)
        conversation = await self._create_conversation(service, learner, store)

        response = await service.ask(conversation_id=conversation.conversation_id, question="What is diversification?")

        assert response.answer.status == TutorAnswerStatus.FALLBACK
        assert tutor_model.calls == 2  # one retry, per spec's "allow one correction attempt"

    async def test_nonexistent_conversation_raises(self) -> None:
        uow_factory, _store = _make_uow_factory()
        service, _r, _m = _build_service(uow_factory)
        with pytest.raises(TutorConversationNotFoundError):
            await service.ask(conversation_id=uuid4(), question="What is diversification?")

    async def test_closed_conversation_raises(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        service, _r, _m = _build_service(uow_factory)
        conversation = await self._create_conversation(service, learner, store)
        await service.close_conversation(conversation.conversation_id)
        with pytest.raises(TutorConversationNotActiveError):
            await service.ask(conversation_id=conversation.conversation_id, question="What is diversification?")


@pytest.mark.asyncio
async def test_close_conversation_sets_closed_status() -> None:
    uow_factory, store = _make_uow_factory()
    learner = _learner()
    store["learners"][learner.learner_id] = learner
    service, _r, _m = _build_service(uow_factory)
    context = TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=learner.learner_id)
    conversation = await service.create_conversation(learner_id=learner.learner_id, context=context)

    closed = await service.close_conversation(conversation.conversation_id)
    assert closed.status == TutorConversationStatus.CLOSED
    assert closed.closed_at == NOW
