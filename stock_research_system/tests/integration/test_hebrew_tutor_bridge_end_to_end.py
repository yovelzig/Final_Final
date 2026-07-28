"""End-to-end PostgreSQL integration tests for the Phase G2E2A Hebrew
question bridge.

Proves the whole path against the real database and the real English
approved corpus: a Hebrew question is persisted verbatim (no UTF-8
corruption), translated once into a canned English retrieval query, the
real hybrid retriever returns real approved English chunks for that query,
the answer comes back in Hebrew, and every citation resolves to an
actually-persisted English chunk row.

Everything external is faked deterministically - the language service's
translation is canned, the tutor model is scripted, and embeddings use the
existing 384-dimension deterministic fake adapter. No network call is made
anywhere in this file. When the PostgreSQL test database is unreachable
every test here skips cleanly (see `tests/integration/conftest.py`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from stock_research_core.application.ai_tutor.chunking import HeadingAwareWordChunker
from stock_research_core.application.ai_tutor.guardrails import RuleBasedTutorGuardrail
from stock_research_core.application.ai_tutor.knowledge_ingestion import KnowledgeIngestionService
from stock_research_core.application.ai_tutor.models import TutorContext, TutorModelResult
from stock_research_core.application.ai_tutor.prompt_builder import GroundedTutorPromptBuilder
from stock_research_core.application.ai_tutor.retrieval import HybridKnowledgeRetriever
from stock_research_core.application.ai_tutor.service import GroundedAITutorService
from stock_research_core.application.ai_tutor.sufficiency import DisabledKnowledgeSufficiencyGate
from stock_research_core.application.exceptions import LanguageServiceError
from stock_research_core.application.language.detection import detect_language
from stock_research_core.application.language.enums import DetectedLanguage, LocalizedMessageKey
from stock_research_core.application.language.localization import localize
from stock_research_core.application.language.models import TranslationResult
from stock_research_core.domain.ai_tutor.enums import (
    KnowledgeApprovalStatus,
    TutorAnswerStatus,
    TutorContextType,
    TutorProviderType,
)
from stock_research_core.domain.ai_tutor.models import (
    EXACT_ADVICE_REFUSAL_HE,
    EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE,
)
from stock_research_core.domain.learning.models import LearnerProfile
from stock_research_core.domain.operations.enums import BackgroundJobType
from stock_research_core.infrastructure.ai_tutor.deterministic_fake_embeddings import (
    DeterministicFakeEmbeddingAdapter,
)
from stock_research_core.infrastructure.ai_tutor.extractive_tutor import DeterministicExtractiveTutor

pytestmark = pytest.mark.integration

_HEBREW_QUESTION = "מה זה פיזור סיכונים בתיק השקעות?"
_CANNED_ENGLISH_QUERY = "diversification portfolio risk single asset"
_HEBREW_ANSWER = "פיזור סיכונים הוא פיזור ההשקעות בין נכסים שונים, כדי להקטין את התלות בנכס בודד [1]."
_ENGLISH_ANSWER = "Diversification spreads investments across assets to reduce reliance on any single asset [1]."


@pytest.fixture
def diversification_note(tmp_path: Path) -> Path:
    """An approved ENGLISH knowledge document - the corpus is deliberately
    never translated or re-ingested for this feature."""
    path = tmp_path / "diversification.md"
    path.write_text(
        "# Diversification\n\n"
        "Diversification is a risk-management strategy that mixes a variety of investments "
        "within a portfolio. It reduces reliance on any single asset, but it does not "
        "guarantee against losses.\n\n"
        "## Why It Matters\n\n"
        "Concentrating holdings in one security increases exposure to that security's "
        "specific risk.\n",
        encoding="utf-8",
    )
    return path


class CannedLanguageService:
    """Satisfies `LanguageServicePort`. `detect_language`/`localize` are the
    real pure implementations (there is nothing to fake about a Unicode
    range scan or a fixed string table); the single network-touching
    method returns a canned bounded English query, or fails."""

    def __init__(self, *, translated_query: str = _CANNED_ENGLISH_QUERY, raise_error: bool = False) -> None:
        self._translated_query = translated_query
        self._raise_error = raise_error
        self.translate_calls: list[str] = []

    def detect_language(self, text: str) -> DetectedLanguage:
        return detect_language(text)

    def localize(self, key: LocalizedMessageKey, *, language: DetectedLanguage) -> str:
        return localize(key, language=language)

    async def translate_to_english_query(
        self, text: str, *, source_language: DetectedLanguage
    ) -> TranslationResult:
        self.translate_calls.append(text)
        if self._raise_error:
            raise LanguageServiceError("translation unavailable (test)")
        return TranslationResult(
            translated_query=self._translated_query, source_language=source_language,
            translation_policy_version="integration-test-v1",
        )


class ScriptedHebrewTutorModel:
    """A Hebrew-capable stand-in for a real LLM provider: cites whatever
    the retriever actually returned, so citation validation is exercised
    for real rather than bypassed."""

    provider_type = TutorProviderType.OPENAI_COMPATIBLE

    def __init__(self, answers: list[str] | None = None) -> None:
        self._answers = answers or [_HEBREW_ANSWER]
        self.calls = 0
        self.questions_seen: list[str] = []

    async def generate(self, request):
        self.questions_seen.append(request.user_question)
        answer = self._answers[min(self.calls, len(self._answers) - 1)]
        self.calls += 1
        return TutorModelResult(
            answer_markdown=answer,
            cited_chunk_ids=[c.chunk.chunk_id for c in request.retrieved_candidates][:1],
            provider_type=self.provider_type, model_name="scripted-hebrew-llm-v1",
        )


class RecordingRetriever:
    """Wraps the REAL `HybridKnowledgeRetriever` (real embeddings, real
    SQL) and records the query text it was actually searched with."""

    def __init__(self, inner: HybridKnowledgeRetriever) -> None:
        self._inner = inner
        self.queries: list[str] = []

    async def retrieve(self, *, query: str, context: TutorContext, top_k: int = 8):
        self.queries.append(query)
        return await self._inner.retrieve(query=query, context=context, top_k=top_k)


async def _ingest_english_corpus(uow_factory, note: Path, embedding_provider) -> None:
    ingestion_service = KnowledgeIngestionService(
        unit_of_work_factory=uow_factory, chunker=HeadingAwareWordChunker(),
        embedding_provider=embedding_provider,
    )
    summary = await ingestion_service.ingest_local_document(
        file_path=note, source_title=f"Hebrew Bridge Corpus {uuid4()}",
        approval_status=KnowledgeApprovalStatus.APPROVED, skill_ids=[],
        available_at=datetime.now(timezone.utc),
    )
    assert summary.chunks_created >= 1
    assert summary.embeddings_created >= 1


def _build_service(
    uow_factory,
    *,
    embedding_provider,
    language_service,
    language_service_enabled: bool = True,
    tutor_model=None,
):
    retriever = RecordingRetriever(
        HybridKnowledgeRetriever(unit_of_work_factory=uow_factory, embedding_provider=embedding_provider)
    )
    service = GroundedAITutorService(
        unit_of_work_factory=uow_factory, retriever=retriever,
        tutor_model=tutor_model or ScriptedHebrewTutorModel(),
        guardrail=RuleBasedTutorGuardrail(), prompt_builder=GroundedTutorPromptBuilder(),
        sufficiency_gate=DisabledKnowledgeSufficiencyGate(),
        language_service=language_service, language_service_enabled=language_service_enabled,
    )
    return service, retriever


async def _create_learner_and_conversation(uow_factory, service):
    async with uow_factory() as uow:
        learner = await uow.learners.create(LearnerProfile(display_name="Hebrew Bridge Learner"))
        await uow.commit()
    context = TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=learner.learner_id)
    conversation = await service.create_conversation(learner_id=learner.learner_id, context=context)
    return learner, conversation


async def _persisted_chunk_ids(uow_factory) -> set[UUID]:
    from stock_research_core.infrastructure.database.orm.knowledge_chunk import KnowledgeChunkORM

    async with uow_factory() as uow:
        result = await uow._session.execute(select(KnowledgeChunkORM.chunk_id))  # noqa: SLF001 - read-only assertion
        return set(result.scalars().all())


class TestHebrewQuestionOverTheEnglishCorpus:
    async def test_hebrew_question_is_answered_in_hebrew_over_english_chunks(
        self, uow_factory, diversification_note: Path
    ) -> None:
        embedding_provider = DeterministicFakeEmbeddingAdapter()
        await _ingest_english_corpus(uow_factory, diversification_note, embedding_provider)
        language_service = CannedLanguageService()
        service, retriever = _build_service(
            uow_factory, embedding_provider=embedding_provider, language_service=language_service,
        )
        _learner, conversation = await _create_learner_and_conversation(uow_factory, service)

        response = await service.ask(
            conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION
        )

        assert language_service.translate_calls == [_HEBREW_QUESTION]
        assert retriever.queries == [_CANNED_ENGLISH_QUERY]
        assert response.answer.status == TutorAnswerStatus.VALIDATED
        assert detect_language(response.answer.answer_markdown) == DetectedLanguage.HE

    async def test_citations_resolve_to_actually_persisted_english_chunks(
        self, uow_factory, diversification_note: Path
    ) -> None:
        embedding_provider = DeterministicFakeEmbeddingAdapter()
        await _ingest_english_corpus(uow_factory, diversification_note, embedding_provider)
        service, _retriever = _build_service(
            uow_factory, embedding_provider=embedding_provider, language_service=CannedLanguageService(),
        )
        _learner, conversation = await _create_learner_and_conversation(uow_factory, service)

        response = await service.ask(
            conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION
        )

        assert len(response.citations) >= 1
        english_source_text = diversification_note.read_text(encoding="utf-8")
        for citation in response.citations:
            assert citation.excerpt in english_source_text

        async with uow_factory() as uow:
            answers = await uow.tutor_answers.list_answers_for_conversation(conversation.conversation_id)
            stored_citations = await uow.tutor_answers.list_citations_for_answer(answers[0].answer_id)
        persisted_chunk_ids = await _persisted_chunk_ids(uow_factory)
        assert stored_citations
        for citation in stored_citations:
            assert citation.chunk_id in persisted_chunk_ids

    async def test_hebrew_text_round_trips_through_postgresql_without_corruption(
        self, uow_factory, diversification_note: Path
    ) -> None:
        embedding_provider = DeterministicFakeEmbeddingAdapter()
        await _ingest_english_corpus(uow_factory, diversification_note, embedding_provider)
        service, _retriever = _build_service(
            uow_factory, embedding_provider=embedding_provider, language_service=CannedLanguageService(),
        )
        _learner, conversation = await _create_learner_and_conversation(uow_factory, service)

        await service.ask(conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION)

        async with uow_factory() as uow:
            messages = await uow.tutor_conversations.list_recent_messages(
                conversation.conversation_id, limit=10
            )
            answers = await uow.tutor_answers.list_answers_for_conversation(conversation.conversation_id)

        user_messages = [m.content for m in messages if m.role.value == "USER"]
        assert user_messages == [_HEBREW_QUESTION]  # byte-for-byte, including the '?'
        assert answers[0].answer_markdown == _HEBREW_ANSWER

    async def test_the_translation_is_never_persisted_as_a_message_or_citation(
        self, uow_factory, diversification_note: Path
    ) -> None:
        embedding_provider = DeterministicFakeEmbeddingAdapter()
        await _ingest_english_corpus(uow_factory, diversification_note, embedding_provider)
        service, _retriever = _build_service(
            uow_factory, embedding_provider=embedding_provider, language_service=CannedLanguageService(),
        )
        _learner, conversation = await _create_learner_and_conversation(uow_factory, service)

        response = await service.ask(
            conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION
        )

        async with uow_factory() as uow:
            messages = await uow.tutor_conversations.list_recent_messages(
                conversation.conversation_id, limit=10
            )
        assert all(_CANNED_ENGLISH_QUERY not in message.content for message in messages)
        for citation in response.citations:
            assert _CANNED_ENGLISH_QUERY not in citation.excerpt
            assert _CANNED_ENGLISH_QUERY != citation.source_title

    async def test_the_model_is_prompted_with_the_original_hebrew_question(
        self, uow_factory, diversification_note: Path
    ) -> None:
        """The translation drives retrieval only - the learner's actual
        question is what the model is asked to answer."""
        embedding_provider = DeterministicFakeEmbeddingAdapter()
        await _ingest_english_corpus(uow_factory, diversification_note, embedding_provider)
        tutor_model = ScriptedHebrewTutorModel()
        service, _retriever = _build_service(
            uow_factory, embedding_provider=embedding_provider,
            language_service=CannedLanguageService(), tutor_model=tutor_model,
        )
        _learner, conversation = await _create_learner_and_conversation(uow_factory, service)

        await service.ask(conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION)

        assert tutor_model.questions_seen == [_HEBREW_QUESTION]

    async def test_the_retrieval_run_records_the_english_query_it_searched_with(
        self, uow_factory, diversification_note: Path
    ) -> None:
        """The audit row must reflect what was really searched, so a
        reviewer can reproduce the retrieval."""
        embedding_provider = DeterministicFakeEmbeddingAdapter()
        await _ingest_english_corpus(uow_factory, diversification_note, embedding_provider)
        service, _retriever = _build_service(
            uow_factory, embedding_provider=embedding_provider, language_service=CannedLanguageService(),
        )
        _learner, conversation = await _create_learner_and_conversation(uow_factory, service)

        response = await service.ask(
            conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION
        )

        async with uow_factory() as uow:
            run = await uow.tutor_retrieval.get_run(response.answer.retrieval_run_id)
        assert run is not None
        assert run.query_text == _CANNED_ENGLISH_QUERY


class TestAnswerLanguageEnforcementEndToEnd:
    async def test_an_english_answer_to_a_hebrew_question_is_repaired(
        self, uow_factory, diversification_note: Path
    ) -> None:
        embedding_provider = DeterministicFakeEmbeddingAdapter()
        await _ingest_english_corpus(uow_factory, diversification_note, embedding_provider)
        tutor_model = ScriptedHebrewTutorModel([_ENGLISH_ANSWER, _HEBREW_ANSWER])
        service, _retriever = _build_service(
            uow_factory, embedding_provider=embedding_provider,
            language_service=CannedLanguageService(), tutor_model=tutor_model,
        )
        _learner, conversation = await _create_learner_and_conversation(uow_factory, service)

        response = await service.ask(
            conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION
        )

        assert tutor_model.calls == 2
        assert response.answer.status == TutorAnswerStatus.VALIDATED
        assert response.answer.answer_markdown == _HEBREW_ANSWER

    async def test_a_persistently_english_answer_falls_back_in_hebrew(
        self, uow_factory, diversification_note: Path
    ) -> None:
        embedding_provider = DeterministicFakeEmbeddingAdapter()
        await _ingest_english_corpus(uow_factory, diversification_note, embedding_provider)
        tutor_model = ScriptedHebrewTutorModel([_ENGLISH_ANSWER, _ENGLISH_ANSWER])
        service, _retriever = _build_service(
            uow_factory, embedding_provider=embedding_provider,
            language_service=CannedLanguageService(), tutor_model=tutor_model,
        )
        _learner, conversation = await _create_learner_and_conversation(uow_factory, service)

        response = await service.ask(
            conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION
        )

        assert tutor_model.calls == 2  # one generation plus exactly one repair
        assert response.answer.status == TutorAnswerStatus.FALLBACK
        assert response.answer.answer_markdown == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE
        assert response.citations == []


class TestFailClosedEndToEnd:
    async def test_translation_failure_never_reaches_retrieval_or_the_model(
        self, uow_factory, diversification_note: Path
    ) -> None:
        embedding_provider = DeterministicFakeEmbeddingAdapter()
        await _ingest_english_corpus(uow_factory, diversification_note, embedding_provider)
        tutor_model = ScriptedHebrewTutorModel()
        service, retriever = _build_service(
            uow_factory, embedding_provider=embedding_provider,
            language_service=CannedLanguageService(raise_error=True), tutor_model=tutor_model,
        )
        _learner, conversation = await _create_learner_and_conversation(uow_factory, service)

        response = await service.ask(
            conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION
        )

        assert retriever.queries == []
        assert tutor_model.calls == 0
        assert response.answer.status == TutorAnswerStatus.FALLBACK
        assert response.answer.answer_markdown == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE

    async def test_an_unsafe_hebrew_question_is_refused_in_hebrew(
        self, uow_factory, diversification_note: Path
    ) -> None:
        embedding_provider = DeterministicFakeEmbeddingAdapter()
        await _ingest_english_corpus(uow_factory, diversification_note, embedding_provider)
        language_service = CannedLanguageService()
        tutor_model = ScriptedHebrewTutorModel()
        service, retriever = _build_service(
            uow_factory, embedding_provider=embedding_provider, language_service=language_service,
            tutor_model=tutor_model,
        )
        _learner, conversation = await _create_learner_and_conversation(uow_factory, service)

        response = await service.ask(
            conversation_id=conversation.conversation_id, question="איזו מניה כדאי לי לקנות?"
        )

        assert response.answer.status == TutorAnswerStatus.REJECTED
        assert response.answer.answer_markdown == EXACT_ADVICE_REFUSAL_HE
        assert language_service.translate_calls == []
        assert retriever.queries == []
        assert tutor_model.calls == 0


class TestFeatureFlagDisabledPreservesExistingBehavior:
    async def test_english_question_is_answered_exactly_as_before(
        self, uow_factory, diversification_note: Path
    ) -> None:
        """With the shared flag off and the pre-existing extractive tutor,
        an English question must behave exactly as `test_ai_tutor_end_to_end`
        already proves - the bridge adds nothing to this path."""
        embedding_provider = DeterministicFakeEmbeddingAdapter()
        await _ingest_english_corpus(uow_factory, diversification_note, embedding_provider)
        language_service = CannedLanguageService()
        service, retriever = _build_service(
            uow_factory, embedding_provider=embedding_provider, language_service=language_service,
            language_service_enabled=False, tutor_model=DeterministicExtractiveTutor(),
        )
        _learner, conversation = await _create_learner_and_conversation(uow_factory, service)

        response = await service.ask(
            conversation_id=conversation.conversation_id, question="What is diversification?"
        )

        assert language_service.translate_calls == []
        assert retriever.queries == ["What is diversification?"]
        assert response.answer.status == TutorAnswerStatus.VALIDATED
        assert len(response.citations) >= 1

    async def test_hebrew_question_never_calls_the_language_service_at_all(
        self, uow_factory, diversification_note: Path
    ) -> None:
        embedding_provider = DeterministicFakeEmbeddingAdapter()
        await _ingest_english_corpus(uow_factory, diversification_note, embedding_provider)
        language_service = CannedLanguageService()
        service, _retriever = _build_service(
            uow_factory, embedding_provider=embedding_provider, language_service=language_service,
            language_service_enabled=False, tutor_model=DeterministicExtractiveTutor(),
        )
        _learner, conversation = await _create_learner_and_conversation(uow_factory, service)

        await service.ask(conversation_id=conversation.conversation_id, question=_HEBREW_QUESTION)

        assert language_service.translate_calls == []


class TestRealWorkerRegistryComposesTheLanguageService:
    """Req. 10's last bullet, asserted through the REAL worker composition
    root rather than a directly-constructed handler - see
    `tests/unit/test_worker_language_composition.py` for the full set."""

    def test_live_research_handler_receives_the_configured_language_service(self) -> None:
        from stock_research_core.infrastructure.ai_tutor.config import EmbeddingSettings, TutorModelSettings
        from stock_research_core.infrastructure.database.config import DatabaseSettings
        from stock_research_core.infrastructure.language.config import LanguageServiceSettings
        from stock_research_core.infrastructure.language.llm_backed_language_service import (
            LlmBackedLanguageService,
        )
        from stock_research_core.infrastructure.operations import celery_tasks
        from stock_research_core.infrastructure.operations.config import OperationsSettings

        previous_context = celery_tasks._worker_context
        celery_tasks._worker_context = None
        try:
            context = celery_tasks._build_worker_context(
                database_settings=DatabaseSettings(
                    database_url="postgresql+asyncpg://user:password@localhost:5433/never_connected"
                ),
                embedding_settings=EmbeddingSettings(
                    embedding_provider="deterministic_fake", embedding_dimension=8
                ),
                operations_settings=OperationsSettings(
                    redis_url="redis://localhost:6379/0", metrics_enabled=False
                ),
                language_service_settings=LanguageServiceSettings(
                    hebrew_query_bridge_enabled=True, language_service_provider="llm_backed",
                    language_service_base_url="https://translation.invalid/v1",
                    language_service_api_key="integration-test-key-never-real",
                    language_service_model_name="test-translation-model",
                ),
                tutor_model_settings=TutorModelSettings(tutor_model_provider="extractive"),
            )
            handler = context.registry.get(BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION).handler
            assert isinstance(handler._language_service, LlmBackedLanguageService)
            assert handler._language_service is context.language_service
            assert handler._language_service_enabled is True
        finally:
            celery_tasks._worker_context = previous_context
