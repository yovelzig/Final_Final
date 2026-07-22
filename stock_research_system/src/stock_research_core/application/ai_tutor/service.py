"""`GroundedAITutorService`: the central grounded-RAG tutor orchestrator.

Composes a `KnowledgeRetrieverPort`, `TutorModelPort`,
`TutorGuardrailPort`, and `TutorPromptBuilderPort` behind a single
`ask()` entry point. Every answer path (refuse / fallback / grounded)
goes through the same guardrail before anything is shown to a learner,
and every grounded answer's citations are built directly from the
retrieved chunk content, never invented.

`ask()` accepts an optional `context` override so `LessonTutorService`,
`ScenarioTutorService`, and `PortfolioTutorService` can supply freshly
computed structured context (lesson/scenario/portfolio metrics) on
every call without this service duplicating those calculations itself
(spec ss23/ss24: "do not duplicate scenario/portfolio calculations").
When omitted, a minimal context is reconstructed from the persisted
`TutorConversation` row - sufficient for `GENERAL_EDUCATION` chat.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from stock_research_core.application.ai_tutor.models import (
    LearnerSafeCitation,
    RetrievalCandidate,
    TutorContext,
    TutorResponse,
)
from stock_research_core.application.ai_tutor.ports import (
    KnowledgeRetrieverPort,
    TutorGuardrailPort,
    TutorModelPort,
    TutorPromptBuilderPort,
)
from stock_research_core.application.exceptions import (
    InactiveLearnerError,
    LearnerNotFoundError,
    TutorConversationNotActiveError,
    TutorConversationNotFoundError,
)
from stock_research_core.domain.ai_tutor.enums import (
    GroundingStatus,
    TutorAnswerStatus,
    TutorConversationStatus,
    TutorGuardrailAction,
    TutorMessageRole,
)
from stock_research_core.domain.ai_tutor.models import (
    EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
    TutorAnswer,
    TutorCitation,
    TutorConversation,
    TutorGuardrailDecision,
    TutorKnowledgeGap,
    TutorMessage,
)
from stock_research_core.domain.models import utc_now

TUTOR_POLICY_VERSION = "grounded-ai-tutor-v1"
DEFAULT_TOP_K = 8
DEFAULT_HISTORY_MESSAGE_LIMIT = 10
DEFAULT_HISTORY_CHARACTER_BUDGET = 6_000
_MAX_CITATION_EXCERPT_LENGTH = 300
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
_WHITESPACE_PATTERN = re.compile(r"\s+")

Clock = Callable[[], datetime]


class GroundedAITutorService:
    """Orchestrates one grounded tutor conversation end to end."""

    policy_version = TUTOR_POLICY_VERSION

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], Any],
        retriever: KnowledgeRetrieverPort,
        tutor_model: TutorModelPort,
        guardrail: TutorGuardrailPort,
        prompt_builder: TutorPromptBuilderPort,
        clock: Clock = utc_now,
        history_message_limit: int = DEFAULT_HISTORY_MESSAGE_LIMIT,
        history_character_budget: int = DEFAULT_HISTORY_CHARACTER_BUDGET,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._retriever = retriever
        self._tutor_model = tutor_model
        self._guardrail = guardrail
        self._prompt_builder = prompt_builder
        self._clock = clock
        self._history_message_limit = history_message_limit
        self._history_character_budget = history_character_budget

    # -- conversation lifecycle -----------------------------------------------

    async def create_conversation(self, *, learner_id: UUID, context: TutorContext) -> TutorConversation:
        async with self._unit_of_work_factory() as uow:
            learner = await uow.learners.get(learner_id)
            if learner is None:
                raise LearnerNotFoundError(f"No learner found with id '{learner_id}'.")
            if not learner.active:
                raise InactiveLearnerError(f"Learner '{learner_id}' is not active.")

            conversation = TutorConversation(
                learner_id=learner_id,
                context_type=context.context_type,
                lesson_id=context.lesson_id,
                exercise_id=context.exercise_id,
                scenario_id=context.scenario_id,
                portfolio_id=context.portfolio_id,
                knowledge_cutoff_at=context.knowledge_cutoff_at,
            )
            saved = await uow.tutor_conversations.create_conversation(conversation)
            await uow.commit()
            return saved

    async def close_conversation(self, conversation_id: UUID) -> TutorConversation:
        async with self._unit_of_work_factory() as uow:
            closed = await uow.tutor_conversations.close_conversation(conversation_id, closed_at=self._clock())
            await uow.commit()
            return closed

    # -- asking -----------------------------------------------

    async def ask(
        self,
        *,
        conversation_id: UUID,
        question: str,
        top_k: int = DEFAULT_TOP_K,
        context: TutorContext | None = None,
    ) -> TutorResponse:
        async with self._unit_of_work_factory() as uow:
            conversation = await uow.tutor_conversations.get_conversation(conversation_id)
            if conversation is None:
                raise TutorConversationNotFoundError(f"No tutor conversation found with id '{conversation_id}'.")
            if conversation.status != TutorConversationStatus.ACTIVE:
                raise TutorConversationNotActiveError(f"Tutor conversation '{conversation_id}' is not ACTIVE.")

            user_message = await uow.tutor_conversations.add_message(
                TutorMessage(conversation_id=conversation_id, role=TutorMessageRole.USER, content=question)
            )
            effective_context = context or self._default_context(conversation)

            guardrail_decision = self._guardrail.evaluate_input(
                conversation_id=conversation_id, message=user_message, context=effective_context
            )
            saved_decision = await uow.tutor_guardrails.save_decision(guardrail_decision)

            if saved_decision.action == TutorGuardrailAction.REFUSE:
                response = await self._finalize_refusal(uow, conversation, user_message, saved_decision)
                await uow.commit()
                return response

            if saved_decision.action == TutorGuardrailAction.FALLBACK:
                response = await self._finalize_fallback(
                    uow, conversation, user_message, saved_decision, effective_context, retrieval_run_id=None
                )
                await uow.commit()
                return response

            recent_messages = await self._load_bounded_history(uow, conversation_id)
            # Committed here (rather than only at the end of `ask()`) because
            # the retrieval call below and the answer-persisting block after
            # it each open their own Unit of Work - without this commit, the
            # user message and guardrail decision written above would exist
            # only in this block's uncommitted transaction and be silently
            # rolled back when its session closes, breaking the foreign keys
            # the next block's `tutor_answers`/`tutor_guardrails` rows need.
            await uow.commit()

        # Retrieval runs in its own short-lived Unit of Work (see
        # `HybridKnowledgeRetriever`) - a read-only pass independent of
        # this conversation's write transaction.
        retrieval_run, candidates = await self._retriever.retrieve(
            query=question, context=effective_context, top_k=top_k
        )
        retrieval_run = retrieval_run.model_copy(update={"conversation_id": conversation_id})

        async with self._unit_of_work_factory() as uow:
            saved_run = await uow.tutor_retrieval.save_run(retrieval_run, candidates)

            if not candidates:
                response = await self._finalize_fallback(
                    uow, conversation, user_message, saved_decision, effective_context,
                    retrieval_run_id=saved_run.retrieval_run_id,
                )
                await uow.commit()
                return response

            prompt_request = self._prompt_builder.build(
                question=question, conversation_messages=recent_messages, candidates=candidates,
                context=effective_context,
            )

            model_result = await self._tutor_model.generate(prompt_request)
            grounding_status, issues = self._guardrail.validate_output(
                answer_text=model_result.answer_markdown, cited_chunk_ids=model_result.cited_chunk_ids,
                retrieved_candidates=candidates, context=effective_context,
            )
            if issues:
                model_result = await self._tutor_model.generate(prompt_request)
                grounding_status, issues = self._guardrail.validate_output(
                    answer_text=model_result.answer_markdown, cited_chunk_ids=model_result.cited_chunk_ids,
                    retrieved_candidates=candidates, context=effective_context,
                )

            if issues or grounding_status in (GroundingStatus.INVALID_CITATIONS, GroundingStatus.INSUFFICIENT_EVIDENCE):
                response = await self._finalize_fallback(
                    uow, conversation, user_message, saved_decision, effective_context,
                    retrieval_run_id=saved_run.retrieval_run_id,
                )
                await uow.commit()
                return response

            answer_markdown = model_result.answer_markdown
            if saved_decision.action == TutorGuardrailAction.ALLOW_WITH_BOUNDARY and saved_decision.safe_response_override:
                answer_markdown = f"{saved_decision.safe_response_override}\n\n{answer_markdown}"

            candidates_by_chunk_id = {candidate.chunk.chunk_id: candidate for candidate in candidates}
            now = self._clock()
            answer = TutorAnswer(
                conversation_id=conversation_id,
                request_message_id=user_message.message_id,
                status=TutorAnswerStatus.VALIDATED,
                provider_type=model_result.provider_type,
                answer_markdown=answer_markdown,
                request_category=saved_decision.request_category,
                grounding_status=grounding_status,
                retrieval_run_id=saved_run.retrieval_run_id,
                guardrail_decision_id=saved_decision.decision_id,
                tutor_policy_version=self.policy_version,
                prompt_version=prompt_request.prompt_version,
                model_name=model_result.model_name,
                model_response_id=model_result.model_response_id,
                validated_at=now,
            )
            saved_answer = await uow.tutor_answers.save_answer(answer)

            citations = [
                self._build_citation(saved_answer.answer_id, citation_number, candidates_by_chunk_id[chunk_id])
                for citation_number, chunk_id in enumerate(model_result.cited_chunk_ids, start=1)
                if chunk_id in candidates_by_chunk_id
            ]
            saved_citations = await uow.tutor_answers.save_citations(citations) if citations else []

            await uow.tutor_conversations.add_message(
                TutorMessage(
                    conversation_id=conversation_id, role=TutorMessageRole.ASSISTANT, content=answer_markdown
                )
            )
            await uow.commit()

            return TutorResponse(
                answer=saved_answer,
                citations=[self._to_learner_safe_citation(citation) for citation in saved_citations],
                guardrail=saved_decision,
            )

    # -- internal helpers -----------------------------------------------

    def _default_context(self, conversation: TutorConversation) -> TutorContext:
        return TutorContext(
            context_type=conversation.context_type,
            learner_id=conversation.learner_id,
            lesson_id=conversation.lesson_id,
            exercise_id=conversation.exercise_id,
            scenario_id=conversation.scenario_id,
            portfolio_id=conversation.portfolio_id,
            knowledge_cutoff_at=conversation.knowledge_cutoff_at,
        )

    async def _load_bounded_history(self, uow: Any, conversation_id: UUID) -> list[TutorMessage]:
        messages = await uow.tutor_conversations.list_recent_messages(
            conversation_id, limit=self._history_message_limit
        )
        total_characters = 0
        bounded: list[TutorMessage] = []
        for message in reversed(messages):
            total_characters += len(message.content)
            if total_characters > self._history_character_budget and bounded:
                break
            bounded.append(message)
        bounded.reverse()
        return bounded

    async def _finalize_refusal(
        self, uow: Any, conversation: TutorConversation, user_message: TutorMessage, decision: TutorGuardrailDecision
    ) -> TutorResponse:
        answer = TutorAnswer(
            conversation_id=conversation.conversation_id,
            request_message_id=user_message.message_id,
            status=TutorAnswerStatus.REJECTED,
            provider_type=self._tutor_model.provider_type,
            answer_markdown=decision.safe_response_override,
            request_category=decision.request_category,
            grounding_status=GroundingStatus.INSUFFICIENT_EVIDENCE,
            guardrail_decision_id=decision.decision_id,
            tutor_policy_version=self.policy_version,
            prompt_version="none",
            model_name="tutor-guardrail-v1",
            validated_at=self._clock(),
        )
        saved_answer = await uow.tutor_answers.save_answer(answer)
        await uow.tutor_conversations.add_message(
            TutorMessage(
                conversation_id=conversation.conversation_id, role=TutorMessageRole.ASSISTANT,
                content=decision.safe_response_override,
            )
        )
        return TutorResponse(answer=saved_answer, citations=[], guardrail=decision)

    async def _finalize_fallback(
        self,
        uow: Any,
        conversation: TutorConversation,
        user_message: TutorMessage,
        decision: TutorGuardrailDecision,
        context: TutorContext,
        *,
        retrieval_run_id: UUID | None,
    ) -> TutorResponse:
        answer = TutorAnswer(
            conversation_id=conversation.conversation_id,
            request_message_id=user_message.message_id,
            status=TutorAnswerStatus.FALLBACK,
            provider_type=self._tutor_model.provider_type,
            answer_markdown=EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
            request_category=decision.request_category,
            grounding_status=GroundingStatus.INSUFFICIENT_EVIDENCE,
            retrieval_run_id=retrieval_run_id,
            guardrail_decision_id=decision.decision_id,
            tutor_policy_version=self.policy_version,
            prompt_version="none",
            model_name="tutor-guardrail-v1",
            validated_at=self._clock(),
        )
        saved_answer = await uow.tutor_answers.save_answer(answer)
        await uow.tutor_conversations.add_message(
            TutorMessage(
                conversation_id=conversation.conversation_id, role=TutorMessageRole.ASSISTANT,
                content=EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
            )
        )
        await self._log_knowledge_gap(uow, conversation, user_message, context)
        return TutorResponse(answer=saved_answer, citations=[], guardrail=decision)

    async def _log_knowledge_gap(
        self, uow: Any, conversation: TutorConversation, user_message: TutorMessage, context: TutorContext
    ) -> None:
        normalized = _normalize_question(user_message.content)
        now = self._clock()
        existing = await uow.tutor_knowledge_gaps.get_by_question_and_context(normalized, context.context_type.value)
        if existing is not None:
            gap = existing.model_copy(
                update={"occurrence_count": existing.occurrence_count + 1, "last_seen_at": now}
            )
        else:
            gap = TutorKnowledgeGap(
                learner_id=conversation.learner_id,
                conversation_id=conversation.conversation_id,
                message_id=user_message.message_id,
                normalized_question=normalized,
                context_type=context.context_type,
                target_skill_ids=list(context.target_skill_ids),
                first_seen_at=now,
                last_seen_at=now,
            )
        await uow.tutor_knowledge_gaps.upsert_gap(gap)

    def _build_citation(
        self, answer_id: UUID, citation_number: int, candidate: RetrievalCandidate
    ) -> TutorCitation:
        return TutorCitation(
            answer_id=answer_id,
            chunk_id=candidate.chunk.chunk_id,
            citation_number=citation_number,
            quoted_excerpt=_extract_excerpt(candidate.chunk.content),
            source_title=candidate.source.title,
            document_title=candidate.document.title,
            heading_path=list(candidate.chunk.heading_path),
        )

    @staticmethod
    def _to_learner_safe_citation(citation: TutorCitation) -> LearnerSafeCitation:
        return LearnerSafeCitation(
            citation_number=citation.citation_number,
            source_title=citation.source_title,
            document_title=citation.document_title,
            heading_path=list(citation.heading_path),
            excerpt=citation.quoted_excerpt,
        )


def _normalize_question(text: str) -> str:
    return _WHITESPACE_PATTERN.sub(" ", text).strip().lower()


def _extract_excerpt(chunk_content: str) -> str:
    """A short excerpt guaranteed to be a literal substring of `chunk_content`."""
    first_sentence = next(
        (s.strip() for s in _SENTENCE_SPLIT_PATTERN.split(chunk_content) if s.strip()), chunk_content
    )
    if len(first_sentence) <= _MAX_CITATION_EXCERPT_LENGTH:
        return first_sentence
    return first_sentence[:_MAX_CITATION_EXCERPT_LENGTH].rstrip()
