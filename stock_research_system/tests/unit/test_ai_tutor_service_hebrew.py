"""Unit tests for `GroundedAITutorService`'s Phase G2E2A Hebrew translation
bridge.

Uses the same fake in-memory repository/Unit-of-Work pattern as
`test_ai_tutor_service.py` (duplicated here rather than imported, matching
this test suite's existing per-file self-contained-fakes convention) plus
a fake `LanguageServicePort` whose `translate_to_english_query` can be
configured to succeed or raise `LanguageServiceError`.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from stock_research_core.application.ai_tutor.guardrails import RuleBasedTutorGuardrail
from stock_research_core.application.ai_tutor.models import (
    KnowledgeSufficiencyDecision,
    RetrievalCandidate,
    TutorContext,
    TutorModelResult,
)
from stock_research_core.application.ai_tutor.prompt_builder import GroundedTutorPromptBuilder
from stock_research_core.application.ai_tutor.service import GroundedAITutorService
from stock_research_core.application.ai_tutor.sufficiency import DisabledKnowledgeSufficiencyGate
from stock_research_core.application.exceptions import LanguageServiceError
from stock_research_core.application.language.detection import detect_language as real_detect_language
from stock_research_core.application.language.enums import DetectedLanguage, LocalizedMessageKey
from stock_research_core.application.language.localization import localize as real_localize
from stock_research_core.application.language.models import TranslationResult
from stock_research_core.application.language.query_preparation import LanguageQueryPreparation
from stock_research_core.domain.ai_tutor.enums import (
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
    EXACT_ADVICE_REFUSAL_HE,
    EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
    EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    TutorRetrievalRun,
)
from stock_research_core.domain.learning.enums import DifficultyLevel
from stock_research_core.domain.learning.models import LearnerProfile

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_HASH = hashlib.sha256(b"x").hexdigest()
_HEBREW_QUESTION = "מה זה פיזור סיכונים בתיק השקעות?"

# ---------------------------------------------------------------------------
# Fakes (mirrors test_ai_tutor_service.py)
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


class FakeRetrievalAuditRepository:
    def __init__(self, store: dict) -> None:
        self._store = store

    async def save_run(self, run, candidates):
        self._store[run.retrieval_run_id] = run
        return run


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


class _OpenScopeTracker:
    """Counts how many Unit-of-Work scopes are open at any moment.

    Phase G2E2A req. 5: lets a test observe, at the instant an external
    call is made, whether a database transaction is being held.
    """

    def __init__(self) -> None:
        self.open_scopes = 0
        self.total_scopes_opened = 0
        self.max_concurrent_scopes = 0

    def enter(self) -> None:
        self.open_scopes += 1
        self.total_scopes_opened += 1
        self.max_concurrent_scopes = max(self.max_concurrent_scopes, self.open_scopes)

    def exit(self) -> None:
        self.open_scopes -= 1


class FakeUnitOfWork:
    def __init__(self, store: dict, tracker: _OpenScopeTracker | None = None) -> None:
        self._store = store
        self._tracker = tracker

    async def __aenter__(self):
        if self._tracker is not None:
            self._tracker.enter()
        self.learners = FakeLearnerRepository(self._store["learners"])
        self.tutor_conversations = FakeConversationRepository(self._store["conversations"], self._store["messages"])
        self.tutor_guardrails = FakeGuardrailRepository(self._store["guardrail_decisions"])
        self.tutor_retrieval = FakeRetrievalAuditRepository(self._store["retrieval_runs"])
        self.tutor_answers = FakeTutorAnswerRepository(self._store["answers"], self._store["citations"])
        self.tutor_knowledge_gaps = FakeKnowledgeGapRepository(self._store["knowledge_gaps"])
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._tracker is not None:
            self._tracker.exit()
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def _make_uow_factory(*, tracker: _OpenScopeTracker | None = None):
    store = {
        "learners": {}, "conversations": {}, "messages": {}, "guardrail_decisions": {},
        "retrieval_runs": {}, "answers": {}, "citations": {}, "knowledge_gaps": {},
    }
    return (lambda: FakeUnitOfWork(store, tracker)), store


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
    """`provider_type` is settable per-instance (unlike the EXTRACTIVE-only
    fake in `test_ai_tutor_service.py`) so these tests can exercise both
    the extractive-capability-gate path and a "real LLM" (Hebrew-capable)
    path."""

    def __init__(
        self, result: TutorModelResult | None = None, *, provider_type: TutorProviderType = TutorProviderType.OPENAI_COMPATIBLE,
    ) -> None:
        self.result = result
        self.provider_type = provider_type
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        if self.result is not None:
            return self.result
        candidate_ids = [c.chunk.chunk_id for c in request.retrieved_candidates]
        return TutorModelResult(
            answer_markdown="פיזור סיכונים מפחית תלות בנכס בודד [1].",
            cited_chunk_ids=candidate_ids[:1], provider_type=self.provider_type,
            model_name="fake-llm-v1",
        )


class AlwaysSufficientGate:
    def evaluate(self, *, query: str, candidates, context):
        del query, context
        if not candidates:
            return KnowledgeSufficiencyDecision(sufficient=False, reason_codes=["NO_CANDIDATES"], policy_version="test-v1")
        return KnowledgeSufficiencyDecision(sufficient=True, reason_codes=["TEST_SUFFICIENT"], policy_version="test-v1")


class SpyPromptBuilder:
    """Wraps the real `GroundedTutorPromptBuilder`, recording the
    `language` kwarg of every `build()` call."""

    def __init__(self) -> None:
        self._real = GroundedTutorPromptBuilder()
        self.prompt_version = self._real.prompt_version
        self.calls = 0
        self.languages_seen: list[DetectedLanguage] = []

    def build(self, **kwargs):
        self.calls += 1
        self.languages_seen.append(kwargs.get("language", DetectedLanguage.EN))
        return self._real.build(**kwargs)


class FakeLanguageService:
    """Satisfies `LanguageServicePort`. `detect_language`/`localize`
    delegate to the real pure implementations (never faked - there is
    nothing to fake, they're deterministic); `translate_to_english_query`
    is the only configurable/mockable seam, matching what a real
    translation-capable adapter's *only* network-touching method is."""

    def __init__(self, *, translated_query: str | None = None, raise_error: bool = False) -> None:
        self.translated_query = translated_query
        self.raise_error = raise_error
        self.translate_calls: list[str] = []

    def detect_language(self, text: str) -> DetectedLanguage:
        return real_detect_language(text)

    def localize(self, key: LocalizedMessageKey, *, language: DetectedLanguage) -> str:
        return real_localize(key, language=language)

    async def translate_to_english_query(self, text: str, *, source_language: DetectedLanguage) -> TranslationResult:
        self.translate_calls.append(text)
        if self.raise_error:
            raise LanguageServiceError("translation unavailable (test)")
        return TranslationResult(
            translated_query=self.translated_query or "diversification portfolio risk",
            source_language=source_language, translation_policy_version="test-v1",
        )


class _TrackingLanguageService(FakeLanguageService):
    """Records how many Unit-of-Work scopes were open each time the
    (external, retrying-over-HTTP) translation call was made."""

    def __init__(self, tracker: _OpenScopeTracker, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tracker = tracker
        self.open_scopes_during_translate: list[int] = []

    async def translate_to_english_query(self, text: str, *, source_language: DetectedLanguage) -> TranslationResult:
        self.open_scopes_during_translate.append(self._tracker.open_scopes)
        return await super().translate_to_english_query(text, source_language=source_language)


class _TrackingTutorModel(FakeTutorModel):
    """Same idea for the model call - the other long external call that
    must never be awaited inside a transaction."""

    def __init__(self, tracker: _OpenScopeTracker, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tracker = tracker
        self.open_scopes_during_generate: list[int] = []

    async def generate(self, request):
        self.open_scopes_during_generate.append(self._tracker.open_scopes)
        return await super().generate(request)


class _ScriptedTutorModel:
    """Returns a scripted answer per successive `generate()` call, so a
    test can drive the answer-language repair path deterministically."""

    def __init__(
        self,
        answers: list[str],
        candidate: RetrievalCandidate,
        *,
        provider_type: TutorProviderType = TutorProviderType.OPENAI_COMPATIBLE,
        repair_cited_chunk_ids: list[UUID] | None = None,
    ) -> None:
        self._answers = answers
        self._candidate = candidate
        self.provider_type = provider_type
        self._repair_cited_chunk_ids = repair_cited_chunk_ids
        self.calls = 0
        self.candidate_ids_seen: list[list[UUID]] = []

    async def generate(self, request):
        self.candidate_ids_seen.append([c.chunk.chunk_id for c in request.retrieved_candidates])
        answer = self._answers[min(self.calls, len(self._answers) - 1)]
        is_repair = self.calls > 0
        self.calls += 1
        cited = (
            self._repair_cited_chunk_ids
            if is_repair and self._repair_cited_chunk_ids is not None
            else [self._candidate.chunk.chunk_id]
        )
        return TutorModelResult(
            answer_markdown=answer, cited_chunk_ids=cited, provider_type=self.provider_type,
            model_name="scripted-llm-v1",
        )


def _build_service(
    uow_factory, *, candidates=None, model_result=None, provider_type=TutorProviderType.OPENAI_COMPATIBLE,
    language_service=None, language_service_enabled=True, prompt_builder=None, tutor_model=None,
):
    retriever = FakeRetriever(candidates)
    tutor_model = tutor_model or FakeTutorModel(model_result, provider_type=provider_type)
    guardrail = RuleBasedTutorGuardrail()
    builder = prompt_builder or SpyPromptBuilder()
    service = GroundedAITutorService(
        unit_of_work_factory=uow_factory, retriever=retriever, tutor_model=tutor_model,
        guardrail=guardrail, prompt_builder=builder, sufficiency_gate=AlwaysSufficientGate(), clock=lambda: NOW,
        language_service=language_service if language_service is not None else FakeLanguageService(),
        language_service_enabled=language_service_enabled,
    )
    return service, retriever, tutor_model, builder


def _learner() -> LearnerProfile:
    return LearnerProfile(learner_id=uuid4(), display_name="Test Learner", financial_experience_level=DifficultyLevel.BEGINNER)


async def _create_conversation(service, learner):
    context = TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=learner.learner_id)
    return await service.create_conversation(learner_id=learner.learner_id, context=context)


@pytest.mark.asyncio
class TestEnglishRegression:
    async def test_english_question_with_flag_enabled_never_calls_translate(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        language_service = FakeLanguageService()
        service, retriever, tutor_model, builder = _build_service(
            uow_factory, candidates=[_candidate()], language_service=language_service,
        )
        conversation = await _create_conversation(service, learner)

        response = await service.ask(conversation_id=conversation.conversation_id, question="What is diversification?")

        assert response.answer.status == TutorAnswerStatus.VALIDATED
        assert retriever.calls == ["What is diversification?"]
        assert language_service.translate_calls == []
        assert builder.languages_seen == [DetectedLanguage.EN]

    async def test_feature_flag_disabled_hebrew_question_behaves_like_pre_phase_baseline(self) -> None:
        """The single kill switch: with `language_service_enabled=False`,
        a Hebrew question gets the exact same (English, off-topic
        false-positive) fallback a Hebrew question always got before
        this phase - proving the disabled default changes nothing."""
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        language_service = FakeLanguageService()
        service, retriever, tutor_model, _builder = _build_service(
            uow_factory, candidates=[_candidate()], language_service=language_service, language_service_enabled=False,
        )
        conversation = await _create_conversation(service, learner)

        response = await service.ask(conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION)

        assert response.answer.status == TutorAnswerStatus.FALLBACK
        assert response.answer.answer_markdown == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK
        assert language_service.translate_calls == []
        assert retriever.calls == []


@pytest.mark.asyncio
class TestHebrewTranslationBridge:
    async def test_successful_translation_drives_retrieval_and_sufficiency_gate(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        candidate = _candidate()
        language_service = FakeLanguageService(translated_query="diversification portfolio risk")
        service, retriever, tutor_model, builder = _build_service(
            uow_factory, candidates=[candidate], language_service=language_service,
        )
        conversation = await _create_conversation(service, learner)

        response = await service.ask(conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION)

        assert language_service.translate_calls == [_HEBREW_QUESTION]
        assert retriever.calls == ["diversification portfolio risk"]
        assert response.answer.status == TutorAnswerStatus.VALIDATED
        assert builder.languages_seen == [DetectedLanguage.HE]

    async def test_original_question_preserved_verbatim_in_tutor_message(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        service, _r, _m, _b = _build_service(uow_factory, candidates=[_candidate()])
        conversation = await _create_conversation(service, learner)

        await service.ask(conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION)

        stored_messages = store["messages"][conversation.conversation_id]
        assert stored_messages[0].content == _HEBREW_QUESTION

    async def test_translation_failure_fails_closed_with_the_hebrew_fallback(self) -> None:
        """Phase G2E2A req. 6: a failed translation must stop the request
        dead - no retrieval, no sufficiency gate, no model call - and
        return the exact Hebrew insufficient-evidence text.

        Note the candidate list here is deliberately NON-empty: the old
        behavior searched the English-only corpus with the untranslated
        Hebrew text and relied on that returning nothing. That assumption
        is not safe (an embedding retriever can return arbitrary
        low-relevance neighbors for any query), so the corrected path
        never issues the query at all.
        """
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        language_service = FakeLanguageService(raise_error=True)
        service, retriever, tutor_model, _b = _build_service(
            uow_factory, candidates=[_candidate()], language_service=language_service,
        )
        conversation = await _create_conversation(service, learner)

        response = await service.ask(conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION)

        assert language_service.translate_calls == [_HEBREW_QUESTION]
        assert retriever.calls == []
        assert tutor_model.calls == 0
        assert response.answer.status == TutorAnswerStatus.FALLBACK
        assert response.answer.answer_markdown == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE
        assert response.citations == []

    async def test_translation_is_attempted_exactly_once_per_request(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        language_service = FakeLanguageService(translated_query="diversification portfolio risk")
        service, _r, _m, _b = _build_service(
            uow_factory, candidates=[_candidate()], language_service=language_service,
        )
        conversation = await _create_conversation(service, learner)

        await service.ask(conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION)

        assert len(language_service.translate_calls) == 1

    async def test_the_translation_is_never_persisted_as_the_learner_message(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        language_service = FakeLanguageService(translated_query="diversification portfolio risk")
        service, _r, _m, _b = _build_service(
            uow_factory, candidates=[_candidate()], language_service=language_service,
        )
        conversation = await _create_conversation(service, learner)

        await service.ask(conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION)

        stored_contents = [message.content for message in store["messages"][conversation.conversation_id]]
        assert _HEBREW_QUESTION in stored_contents
        assert "diversification portfolio risk" not in stored_contents

    async def test_citations_map_to_real_retrieved_chunks_never_the_translation(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        candidate = _candidate("Diversification reduces reliance on a single asset.")
        language_service = FakeLanguageService(translated_query="diversification portfolio risk")
        service, _r, _m, _b = _build_service(
            uow_factory, candidates=[candidate], language_service=language_service,
        )
        conversation = await _create_conversation(service, learner)

        response = await service.ask(conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION)

        assert len(response.citations) == 1
        citation = response.citations[0]
        assert citation.source_title == "Approved Source"
        assert "Diversification reduces reliance" in citation.excerpt
        # The translated query text never appears anywhere in the citation.
        assert "diversification portfolio risk" not in citation.excerpt
        assert "diversification portfolio risk" != citation.source_title


@pytest.mark.asyncio
class TestOriginalTextGuardrail:
    async def test_hebrew_buy_sell_refuses_before_any_translation_or_retrieval(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        language_service = FakeLanguageService()
        service, retriever, tutor_model, _b = _build_service(
            uow_factory, candidates=[_candidate()], language_service=language_service,
        )
        conversation = await _create_conversation(service, learner)

        response = await service.ask(
            conversation_id=conversation.conversation_id, question="האם כדאי לי לבצע buy NVDA עכשיו?"
        )

        assert response.answer.status == TutorAnswerStatus.REJECTED
        assert response.answer.answer_markdown == EXACT_ADVICE_REFUSAL_HE
        assert language_service.translate_calls == []  # never translated a message already refused on its own text
        assert retriever.calls == []
        assert tutor_model.calls == 0


@pytest.mark.asyncio
class TestTranslatedTextDefenseInDepth:
    async def test_translated_text_revealing_unsafe_content_escalates_to_refuse(self) -> None:
        """The original Hebrew text alone doesn't match any REFUSE
        pattern (no embedded English trigger words), but its translation
        does - the merge must escalate ALLOW -> REFUSE, never the
        reverse, and the final decision uses the Hebrew-localized text."""
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        # Translated query intentionally contains a buy/sell trigger phrase.
        language_service = FakeLanguageService(translated_query="should I buy NVDA now")
        service, retriever, tutor_model, _b = _build_service(
            uow_factory, candidates=[_candidate()], language_service=language_service,
        )
        conversation = await _create_conversation(service, learner)

        response = await service.ask(conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION)

        assert response.answer.status == TutorAnswerStatus.REJECTED
        assert response.answer.answer_markdown == EXACT_ADVICE_REFUSAL_HE
        assert retriever.calls == []  # escalated to REFUSE before retrieval ever runs
        assert tutor_model.calls == 0

    async def test_translated_text_on_topic_never_downgrades_original_allow(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        language_service = FakeLanguageService(translated_query="diversification portfolio risk")
        service, retriever, tutor_model, _b = _build_service(
            uow_factory, candidates=[_candidate()], language_service=language_service,
        )
        conversation = await _create_conversation(service, learner)

        response = await service.ask(conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION)

        assert response.answer.status == TutorAnswerStatus.VALIDATED
        assert retriever.calls == ["diversification portfolio risk"]


@pytest.mark.asyncio
class TestExtractiveProviderHebrewCapabilityGate:
    async def test_extractive_provider_never_generates_for_hebrew_question(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        language_service = FakeLanguageService(translated_query="diversification portfolio risk")
        service, retriever, tutor_model, _b = _build_service(
            uow_factory, candidates=[_candidate()], provider_type=TutorProviderType.EXTRACTIVE,
            language_service=language_service,
        )
        conversation = await _create_conversation(service, learner)

        response = await service.ask(conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION)

        assert tutor_model.calls == 0
        assert response.answer.status == TutorAnswerStatus.FALLBACK
        assert response.answer.answer_markdown == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE
        assert response.answer.provider_type == TutorProviderType.EXTRACTIVE

    async def test_extractive_provider_still_answers_english_questions_normally(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        service, _r, tutor_model, _b = _build_service(
            uow_factory, candidates=[_candidate()], provider_type=TutorProviderType.EXTRACTIVE,
        )
        conversation = await _create_conversation(service, learner)

        response = await service.ask(conversation_id=conversation.conversation_id, question="What is diversification?")

        assert tutor_model.calls == 1
        assert response.answer.status == TutorAnswerStatus.VALIDATED


@pytest.mark.asyncio
class TestNoDatabaseTransactionIsHeldDuringAnExternalCall:
    """Phase G2E2A req. 5: translation and model generation must happen
    strictly OUTSIDE any open Unit of Work.

    A translation provider retries with backoff over HTTP; holding a
    PostgreSQL connection (and its row locks) for that entire window is
    how a slow provider turns into connection-pool exhaustion. These tests
    assert it structurally rather than by inspecting source text: the
    tracking Unit of Work below records how many scopes are open at the
    moment each external call is made, so the assertion fails if any
    future refactor moves a call back inside a scope.
    """

    async def test_translation_and_generation_both_run_with_zero_open_units_of_work(self) -> None:
        tracker = _OpenScopeTracker()
        uow_factory, store = _make_uow_factory(tracker=tracker)
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        language_service = _TrackingLanguageService(tracker, translated_query="diversification portfolio risk")
        service, _r, tutor_model, _b = _build_service(
            uow_factory, candidates=[_candidate()], language_service=language_service,
            tutor_model=_TrackingTutorModel(tracker),
        )

        await self._ask(service, learner)

        assert language_service.open_scopes_during_translate == [0]
        assert tutor_model.open_scopes_during_generate == [0]

    async def test_at_least_one_unit_of_work_scope_really_was_opened(self) -> None:
        """Guards the assertion above from passing vacuously: if the
        tracker never saw a scope at all, `[0]` would prove nothing."""
        tracker = _OpenScopeTracker()
        uow_factory, store = _make_uow_factory(tracker=tracker)
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        service, _r, _m, _b = _build_service(
            uow_factory, candidates=[_candidate()],
            language_service=FakeLanguageService(translated_query="diversification portfolio risk"),
        )

        await self._ask(service, learner)

        assert tracker.total_scopes_opened >= 4

    async def test_no_two_unit_of_work_scopes_are_ever_nested(self) -> None:
        """Short scopes, not one long scope wrapping the others - a nested
        scope would reintroduce exactly the long-held transaction this
        requirement removes."""
        tracker = _OpenScopeTracker()
        uow_factory, store = _make_uow_factory(tracker=tracker)
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        service, _r, _m, _b = _build_service(
            uow_factory, candidates=[_candidate()],
            language_service=FakeLanguageService(translated_query="diversification portfolio risk"),
        )

        await self._ask(service, learner)

        assert tracker.max_concurrent_scopes == 1

    async def _ask(self, service, learner) -> None:
        conversation = await _create_conversation(service, learner)
        await service.ask(conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION)


@pytest.mark.asyncio
class TestAnswerLanguageEnforcement:
    """Phase G2E2A req. 8: a Hebrew instruction in the prompt is a
    request, not a guarantee - the answer's actual language is validated
    after generation and normal citation validation."""

    async def test_hebrew_request_with_hebrew_answer_is_accepted_without_repair(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        candidate = _candidate()
        model = _ScriptedTutorModel(["פיזור סיכונים מפחית תלות בנכס בודד [1]."], candidate)
        service, _r, _m, _b = _build_service(
            uow_factory, candidates=[candidate], tutor_model=model,
            language_service=FakeLanguageService(translated_query="diversification portfolio risk"),
        )
        conversation = await _create_conversation(service, learner)

        response = await service.ask(conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION)

        assert model.calls == 1
        assert response.answer.status == TutorAnswerStatus.VALIDATED
        assert response.answer.answer_markdown.startswith("פיזור סיכונים")

    async def test_hebrew_request_with_english_answer_is_repaired_once(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        candidate = _candidate()
        model = _ScriptedTutorModel(
            ["Diversification reduces reliance on a single asset [1].", "פיזור סיכונים מפחית תלות בנכס בודד [1]."],
            candidate,
        )
        service, _r, _m, _b = _build_service(
            uow_factory, candidates=[candidate], tutor_model=model,
            language_service=FakeLanguageService(translated_query="diversification portfolio risk"),
        )
        conversation = await _create_conversation(service, learner)

        response = await service.ask(conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION)

        assert model.calls == 2
        assert response.answer.status == TutorAnswerStatus.VALIDATED
        assert response.answer.answer_markdown.startswith("פיזור סיכונים")

    async def test_the_repair_attempt_receives_no_new_sources(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        candidate = _candidate()
        model = _ScriptedTutorModel(
            ["Diversification reduces reliance on a single asset [1].", "פיזור סיכונים מפחית תלות בנכס בודד [1]."],
            candidate,
        )
        service, retriever, _m, _b = _build_service(
            uow_factory, candidates=[candidate], tutor_model=model,
            language_service=FakeLanguageService(translated_query="diversification portfolio risk"),
        )
        conversation = await _create_conversation(service, learner)

        await service.ask(conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION)

        first_sources, repair_sources = model.candidate_ids_seen
        assert repair_sources == first_sources
        assert len(retriever.calls) == 1  # no second retrieval for the repair

    async def test_second_english_answer_falls_back_never_shows_english_to_a_hebrew_learner(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        candidate = _candidate()
        model = _ScriptedTutorModel(
            [
                "Diversification reduces reliance on a single asset [1].",
                "Diversification still reduces reliance on a single asset [1].",
            ],
            candidate,
        )
        service, _r, _m, _b = _build_service(
            uow_factory, candidates=[candidate], tutor_model=model,
            language_service=FakeLanguageService(translated_query="diversification portfolio risk"),
        )
        conversation = await _create_conversation(service, learner)

        response = await service.ask(conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION)

        assert model.calls == 2  # exactly ONE bounded repair attempt, never a third
        assert response.answer.status == TutorAnswerStatus.FALLBACK
        assert response.answer.answer_markdown == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE

    async def test_citation_validation_still_applies_after_a_repair(self) -> None:
        """A repaired answer must not be able to smuggle in a citation
        the first attempt could not have used."""
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        candidate = _candidate()
        model = _ScriptedTutorModel(
            ["Diversification reduces reliance on a single asset [1].", "פיזור סיכונים מפחית תלות בנכס בודד [1]."],
            candidate,
            repair_cited_chunk_ids=[uuid4()],  # not a retrieved chunk
        )
        service, _r, _m, _b = _build_service(
            uow_factory, candidates=[candidate], tutor_model=model,
            language_service=FakeLanguageService(translated_query="diversification portfolio risk"),
        )
        conversation = await _create_conversation(service, learner)

        response = await service.ask(conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION)

        assert response.answer.status == TutorAnswerStatus.FALLBACK
        assert response.answer.answer_markdown == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE

    async def test_english_request_with_english_answer_is_never_language_repaired(self) -> None:
        """The enforcement is Hebrew-only: an English request must not
        newly consult the detector or trigger a second generation."""
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        candidate = _candidate()
        model = _ScriptedTutorModel(["Diversification reduces reliance on a single asset [1]."], candidate)
        service, _r, _m, _b = _build_service(uow_factory, candidates=[candidate], tutor_model=model)
        conversation = await _create_conversation(service, learner)

        response = await service.ask(
            conversation_id=conversation.conversation_id, question="What is diversification?"
        )

        assert model.calls == 1
        assert response.answer.status == TutorAnswerStatus.VALIDATED


@pytest.mark.asyncio
class TestPreparedLanguageReuse:
    """Phase G2E2A req. 3: when the LangGraph coach has already prepared
    this request's bounded English query, the tutor service must reuse it
    instead of issuing a second translation call for the same text."""

    async def test_a_matching_preparation_is_reused_without_translating_again(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        language_service = FakeLanguageService(translated_query="never used - would be a second call")
        service, retriever, _m, _b = _build_service(
            uow_factory, candidates=[_candidate()], language_service=language_service,
        )
        conversation = await _create_conversation(service, learner)
        prepared = LanguageQueryPreparation(
            original_text=_HEBREW_QUESTION, detected_language=DetectedLanguage.HE,
            search_query="diversification portfolio risk", translation_attempted=True, translation_failed=False,
        )

        await service.ask(
            conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION, prepared_language=prepared,
        )

        assert language_service.translate_calls == []
        assert retriever.calls == ["diversification portfolio risk"]

    async def test_a_preparation_for_different_text_is_never_silently_applied(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        language_service = FakeLanguageService(translated_query="diversification portfolio risk")
        service, retriever, _m, _b = _build_service(
            uow_factory, candidates=[_candidate()], language_service=language_service,
        )
        conversation = await _create_conversation(service, learner)
        stale = LanguageQueryPreparation(
            original_text="a different question entirely", detected_language=DetectedLanguage.HE,
            search_query="stale query that must not be used", translation_attempted=True, translation_failed=False,
        )

        await service.ask(
            conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION, prepared_language=stale,
        )

        assert language_service.translate_calls == [_HEBREW_QUESTION]
        assert retriever.calls == ["diversification portfolio risk"]

    async def test_a_failed_preparation_is_reused_and_still_fails_closed(self) -> None:
        uow_factory, store = _make_uow_factory()
        learner = _learner()
        store["learners"][learner.learner_id] = learner
        language_service = FakeLanguageService(raise_error=True)
        service, retriever, tutor_model, _b = _build_service(
            uow_factory, candidates=[_candidate()], language_service=language_service,
        )
        conversation = await _create_conversation(service, learner)
        failed = LanguageQueryPreparation(
            original_text=_HEBREW_QUESTION, detected_language=DetectedLanguage.HE,
            search_query=_HEBREW_QUESTION, translation_attempted=True, translation_failed=True,
        )

        response = await service.ask(
            conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION, prepared_language=failed,
        )

        assert language_service.translate_calls == []  # not retried here either
        assert retriever.calls == []
        assert tutor_model.calls == 0
        assert response.answer.answer_markdown == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE
