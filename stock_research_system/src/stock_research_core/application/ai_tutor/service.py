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

Phase G2E2A: Hebrew questions are supported via a translation-query
bridge, gated entirely by `language_service_enabled` (default `False` -
see `infrastructure.language.config.LanguageServiceSettings`). When
disabled, `ask()` never calls `language_service.detect_language()` at
all, so English behavior is provably unchanged. When enabled: the
learner's *original* text is always what gets persisted
(`TutorMessage.content`) and guardrail-checked first; only a bounded
English translation of it is ever used to drive retrieval and the
Knowledge Sufficiency Gate (`application.language.models.TranslationResult`
is never treated as evidence, never persisted as the learner's own
message, and never appears in a citation); the model is prompted with
the *original* question and instructed to answer in the learner's own
language; citations still map to the real retrieved (English) chunks.

Phase G2E2A correction pass - two structural rules `ask()`'s shape now
enforces:

- **No external call ever runs inside a Unit of Work** (req. 5). `ask()`
  is a sequence of short, explicit write scopes - (1) load/revalidate the
  conversation and persist the learner's original message, (2) persist the
  guardrail decision (and short-circuit refusal/fallback), (3) persist
  retrieval state and run the sufficiency gate, (4) persist the answer,
  citations, and assistant message - with the one bounded translation call
  and every model call happening strictly *between* them. No DB
  connection is ever held while awaiting a provider's HTTP retries.
- **Translation failure fails closed** (req. 6). A Hebrew question whose
  translation failed never reaches retrieval or a model: it returns the
  exact localized Hebrew insufficient-evidence fallback. Nothing relies on
  an untranslated Hebrew embedding query "probably" matching nothing.

Answer-language enforcement (req. 8) closes the last gap: a Hebrew
instruction in the prompt is a request, not a guarantee, so after normal
citation validation a Hebrew-requested answer is checked with the same
shared detector and gets at most ONE bounded repair attempt over the
*same* approved candidates (no new sources) before falling back.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from stock_research_core.application.ai_tutor.guardrails import more_restrictive_decision
from stock_research_core.application.ai_tutor.diagnostics import TutorDiagnosticIssueCode, log_tutor_diagnostic
from stock_research_core.application.ai_tutor.models import (
    LearnerSafeCitation,
    RetrievalCandidate,
    TutorContext,
    TutorModelRequest,
    TutorModelResult,
    TutorResponse,
)
from stock_research_core.application.ai_tutor.ports import (
    KnowledgeRetrieverPort,
    KnowledgeSufficiencyGatePort,
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
from stock_research_core.application.language.enums import DetectedLanguage, LocalizedMessageKey
from stock_research_core.application.language.ports import LanguageServicePort
from stock_research_core.application.language.query_preparation import (
    LanguageQueryPreparation,
    detect_request_language,
    prepare_language_query,
    untranslated_preparation,
)
from stock_research_core.application.language.unavailable_language_service import UnavailableLanguageService
from stock_research_core.domain.ai_tutor.enums import (
    GroundingStatus,
    TutorAnswerStatus,
    TutorConversationStatus,
    TutorGuardrailAction,
    TutorMessageRole,
    TutorProviderType,
)
from stock_research_core.domain.ai_tutor.models import (
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

#: Appended to the *same* prompt for the single bounded answer-language
#: repair attempt (Phase G2E2A req. 8). No new sources, no new candidates,
#: no new retrieval - only an instruction to re-express the same grounded
#: answer, with the same citations, in the learner's own language.
_ANSWER_LANGUAGE_REPAIR_INSTRUCTION = (
    "\nCORRECTION: your previous answer was not written in Hebrew. Rewrite that same answer "
    "entirely in Hebrew (Ãƒâ€”Ã‚Â¢Ãƒâ€”Ã¢â‚¬ËœÃƒâ€”Ã‚Â¨Ãƒâ€”Ã¢â€žÂ¢Ãƒâ€”Ã‚Âª), using only the approved evidence already listed above and the "
    "same bracket citations. Do not add any new fact, source, or citation number that was not "
    "already present.\n"
)

Clock = Callable[[], datetime]

# Maps `RuleBasedTutorGuardrail.validate_output`'s own issue vocabulary
# (guaranteed-return claims, buy/sell instructions, scenario/portfolio
# leaks, hidden-reasoning markers - none of which are themselves one of
# the 10 bounded `TutorDiagnosticIssueCode`s) onto the closest
# diagnostic code, so a real guardrail finding is never silently dropped
# by `log_tutor_diagnostic`'s unknown-code filter. Codes already present
# in `TutorDiagnosticIssueCode.ALL` (e.g. `INVALID_CITATION_CHUNK_ID`,
# `UNVERIFIED_URL`) pass through unchanged.
_GUARDRAIL_ISSUE_TO_DIAGNOSTIC_CODE = {
    "GUARANTEED_RETURN_CLAIM": TutorDiagnosticIssueCode.UNSAFE_GENERATED_OUTPUT,
    "DIRECT_BUY_SELL_INSTRUCTION": TutorDiagnosticIssueCode.UNSAFE_GENERATED_OUTPUT,
    "SCENARIO_FUTURE_INFORMATION_LEAK": TutorDiagnosticIssueCode.UNSAFE_GENERATED_OUTPUT,
    "PORTFOLIO_TRADE_PRESCRIPTION": TutorDiagnosticIssueCode.UNSAFE_GENERATED_OUTPUT,
    "HIDDEN_REASONING_MARKER": TutorDiagnosticIssueCode.UNSAFE_GENERATED_OUTPUT,
}


def _to_diagnostic_issue_codes(guardrail_issues: list[str]) -> list[str]:
    return [_GUARDRAIL_ISSUE_TO_DIAGNOSTIC_CODE.get(issue, issue) for issue in guardrail_issues]


@dataclass(frozen=True)
class _ValidatedGeneration:
    """One model result that passed citation validation and (when the
    learner asked in Hebrew) answer-language validation."""

    model_result: TutorModelResult
    grounding_status: GroundingStatus
    prompt_version: str


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
        sufficiency_gate: KnowledgeSufficiencyGatePort,
        clock: Clock = utc_now,
        history_message_limit: int = DEFAULT_HISTORY_MESSAGE_LIMIT,
        history_character_budget: int = DEFAULT_HISTORY_CHARACTER_BUDGET,
        language_service: LanguageServicePort | None = None,
        language_service_enabled: bool = False,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._retriever = retriever
        self._tutor_model = tutor_model
        self._guardrail = guardrail
        self._prompt_builder = prompt_builder
        # Phase E1: required, explicit at every call site - composition
        # always chooses (`RuleBasedKnowledgeSufficiencyGate` when
        # enabled, `DisabledKnowledgeSufficiencyGate` otherwise/by
        # default). No silent fallback here: every construction site
        # must decide and pass this keyword itself.
        self._sufficiency_gate = sufficiency_gate
        self._clock = clock
        self._history_message_limit = history_message_limit
        self._history_character_budget = history_character_budget
        # Phase G2E2A: `language_service_enabled=False` (the default) is
        # the single kill switch - `ask()` never calls
        # `self._language_service.detect_language()` (or anything else
        # on it) unless this is `True`, so an unconfigured/disabled
        # deployment runs zero new code for any question, English or
        # otherwise. `language_service` still defaults to a real (pure,
        # free) `UnavailableLanguageService` rather than `None` so `ask()`
        # never needs a `None` check.
        self._language_service: LanguageServicePort = language_service or UnavailableLanguageService()
        self._language_service_enabled = language_service_enabled

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
        prepared_language: LanguageQueryPreparation | None = None,
    ) -> TutorResponse:
        """`prepared_language` lets a caller that has *already* performed
        this request's one bounded language-query preparation hand it in
        rather than causing a second translation call for the same text -
        the LangGraph learning coach does exactly this (its
        `evaluate_input_guardrail` node prepares once per run, and every
        route that reaches a tutor service passes that same preparation
        through). It is only reused when it belongs to this exact
        `question`; anything else is re-prepared here, so a stale or
        mismatched preparation can never be silently applied."""
        # -- Unit of Work 1: load/revalidate the conversation and persist
        #    the learner's original message verbatim. No external call
        #    happens inside this (or any other) write scope - req. 5.
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
            await uow.commit()

        # -- Outside every Unit of Work: the ONE bounded language-query
        #    preparation for this request (req. 3/5). Detection is a pure
        #    function of `question` alone; the single translation call is
        #    the only external call here, and no DB connection is held
        #    while it awaits its bounded HTTP retries.
        if prepared_language is not None and prepared_language.original_text == question:
            preparation, guardrail_decision = self._reuse_preparation(
                prepared_language, conversation_id=conversation_id, user_message=user_message,
                context=effective_context,
            )
        else:
            preparation, guardrail_decision = await self._prepare_and_decide(
                conversation_id=conversation_id, user_message=user_message, context=effective_context,
            )

        # -- Unit of Work 2: persist the decision, and short-circuit every
        #    path that must not reach retrieval or a model.
        async with self._unit_of_work_factory() as uow:
            saved_decision = await uow.tutor_guardrails.save_decision(guardrail_decision)

            if saved_decision.action == TutorGuardrailAction.REFUSE:
                response = await self._finalize_refusal(uow, conversation, user_message, saved_decision)
                await uow.commit()
                return response

            # `preparation.translation_failed` fails closed (req. 6): a
            # Hebrew question whose translation failed never reaches
            # retrieval, the sufficiency gate, or a model - it returns the
            # exact localized Hebrew fallback. Nothing here depends on an
            # untranslated Hebrew embedding query happening to match no
            # English chunk.
            if saved_decision.action == TutorGuardrailAction.FALLBACK or preparation.translation_failed:
                response = await self._finalize_fallback(
                    uow, conversation, user_message, saved_decision, effective_context,
                    language=preparation.detected_language, retrieval_run_id=None,
                )
                await uow.commit()
                return response

            recent_messages = await self._load_bounded_history(uow, conversation_id)
            await uow.commit()

        # Retrieval runs in its own short-lived Unit of Work (see
        # `HybridKnowledgeRetriever`) - a read-only pass independent of
        # this conversation's write transactions. `preparation.search_query`
        # is the learner's original `question` unless Hebrew translation ran
        # and succeeded above - never persisted anywhere, only ever used to
        # drive retrieval/sufficiency, per spec ss5/ss6.
        retrieval_run, candidates = await self._retriever.retrieve(
            query=preparation.search_query, context=effective_context, top_k=top_k
        )
        retrieval_run = retrieval_run.model_copy(update={"conversation_id": conversation_id})

        # -- Unit of Work 3: persist retrieval state and run the
        #    (deterministic, local) sufficiency gate.
        async with self._unit_of_work_factory() as uow:
            saved_run = await uow.tutor_retrieval.save_run(retrieval_run, candidates)

            # Phase E1: Knowledge Sufficiency Gate - a distinct checkpoint
            # from the guardrail above, evaluated exactly once for every
            # retrieval result (including an empty candidate list - there
            # is no separate empty-candidate branch here; the composed
            # gate itself decides that case, e.g.
            # `DisabledKnowledgeSufficiencyGate` reproduces the legacy
            # "empty candidates -> fallback" rule directly). Runs after
            # retrieval is saved but before any prompt is built or model
            # is called, closing the gap where a weak/unrelated but
            # non-empty candidate list would otherwise still reach the
            # model. Evaluated against `preparation.search_query` (same text
            # the retriever itself searched with), never the original
            # Hebrew text - the gate's own keyword heuristics are
            # English-only.
            sufficiency_decision = self._sufficiency_gate.evaluate(
                query=preparation.search_query, candidates=candidates, context=effective_context
            )
            # Preserve the extractive/Hebrew fail-closed rule and emit G2D2 safe diagnostics.
            extractive_cannot_answer_hebrew = (
                preparation.is_hebrew and self._tutor_model.provider_type == TutorProviderType.EXTRACTIVE
            )
            if not sufficiency_decision.sufficient or extractive_cannot_answer_hebrew:
                log_tutor_diagnostic(
                    provider_type=self._tutor_model.provider_type, model_name="tutor-guardrail-v1",
                    attempt_number=0, retrieval_candidate_count=len(candidates), cited_id_count=0,
                    issue_codes=[TutorDiagnosticIssueCode.RETRIEVAL_INSUFFICIENT],
                    conversation_id=conversation_id,
                )
                response = await self._finalize_fallback(
                    uow, conversation, user_message, saved_decision, effective_context,
                    language=preparation.detected_language, retrieval_run_id=saved_run.retrieval_run_id,
                )
                await uow.commit()
                return response

            await uow.commit()

        # -- Outside every Unit of Work: prompt construction, model
        #    generation, the bounded citation-repair retry, and the bounded
        #    answer-language repair attempt (req. 5/8).
        generation = await self._generate_validated_answer(
            question=question, recent_messages=recent_messages, candidates=candidates,
            context=effective_context, preparation=preparation,
        )

        # -- Unit of Work 4: persist the answer, its citations, and the
        #    assistant message (or the fallback, when generation failed
        #    validation).
        async with self._unit_of_work_factory() as uow:
            if generation is None:
                response = await self._finalize_fallback(
                    uow, conversation, user_message, saved_decision, effective_context,
                    language=preparation.detected_language, retrieval_run_id=saved_run.retrieval_run_id,
                )
                await uow.commit()
                return response

            model_result = generation.model_result
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
                grounding_status=generation.grounding_status,
                retrieval_run_id=saved_run.retrieval_run_id,
                guardrail_decision_id=saved_decision.decision_id,
                tutor_policy_version=self.policy_version,
                prompt_version=generation.prompt_version,
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

    def _evaluate_original(
        self,
        *,
        conversation_id: UUID,
        user_message: TutorMessage,
        context: TutorContext,
        language: DetectedLanguage,
    ) -> TutorGuardrailDecision:
        """The guardrail decision on the learner's *own* words (req. 4).

        Pure, local, and free of any transaction or provider call. Runs
        the Hebrew-script safety patterns as well as the English ones, so
        a pure Hebrew unsafe request is refused from the learner's own
        words even when translation is unavailable.

        The off-topic vocabulary check is skipped for Hebrew text: its
        vocabulary is English-only, so zero `[a-z]` tokens is "no data",
        not "off-topic evidence" (the Knowledge Sufficiency Gate over the
        translated query is the real topic-relevance filter for Hebrew).
        """
        return self._guardrail.evaluate_input(
            conversation_id=conversation_id, message=user_message, context=context,
            language=language, apply_topic_vocabulary_check=language != DetectedLanguage.HE,
        )

    def _decide_with_translation(
        self,
        *,
        conversation_id: UUID,
        user_message: TutorMessage,
        context: TutorContext,
        preparation: LanguageQueryPreparation,
        original_decision: TutorGuardrailDecision,
    ) -> TutorGuardrailDecision:
        """Defense in depth: the *same* deterministic guardrail evaluated
        against the bounded English query, with the more restrictive
        decision winning (req. 4).

        This pass skips the vocabulary check because a bounded,
        keyword-shaped retrieval query legitimately lacks the connective
        finance vocabulary the check looks for. It can therefore only
        escalate toward REFUSE - the original-text decision is never
        downgraded.
        """
        if not preparation.translation_succeeded:
            return original_decision

        translated_message = user_message.model_copy(update={"content": preparation.search_query})
        translated_decision = self._guardrail.evaluate_input(
            conversation_id=conversation_id, message=translated_message, context=context,
            language=preparation.detected_language, apply_topic_vocabulary_check=False,
        )
        return more_restrictive_decision(original_decision, translated_decision)

    async def _prepare_and_decide(
        self, *, conversation_id: UUID, user_message: TutorMessage, context: TutorContext,
    ) -> tuple[LanguageQueryPreparation, TutorGuardrailDecision]:
        """This request's one language preparation and its guardrail
        decision, in the order that keeps a refused question off the wire.

        Detection is pure, so the guardrail runs on the learner's own
        words FIRST. A request refused there is never translated at all:
        there is nothing to retrieve for it, and an unsafe question should
        not be handed to a third-party translation provider just to
        produce a query no one will use.

        Otherwise exactly one translation is attempted, and its result
        feeds the defense-in-depth pass above. No external call happens
        inside a Unit of Work (req. 5).
        """
        language = detect_request_language(
            self._language_service, enabled=self._language_service_enabled, text=user_message.content
        )
        original_decision = self._evaluate_original(
            conversation_id=conversation_id, user_message=user_message, context=context, language=language,
        )
        if original_decision.action == TutorGuardrailAction.REFUSE:
            return untranslated_preparation(user_message.content, language), original_decision

        preparation = await prepare_language_query(
            self._language_service, enabled=self._language_service_enabled,
            text=user_message.content, detected_language=language,
        )
        decision = self._decide_with_translation(
            conversation_id=conversation_id, user_message=user_message, context=context,
            preparation=preparation, original_decision=original_decision,
        )
        return preparation, decision

    def _reuse_preparation(
        self,
        prepared_language: LanguageQueryPreparation,
        *,
        conversation_id: UUID,
        user_message: TutorMessage,
        context: TutorContext,
    ) -> tuple[LanguageQueryPreparation, TutorGuardrailDecision]:
        """Re-derive this request's guardrail decision from a preparation
        the caller (the LangGraph coach) already made, without translating
        again.

        The decision itself is deliberately NOT passed in and reused: it
        is cheap, deterministic, and belongs to this conversation's own
        `user_message`, so recomputing it here keeps the persisted
        `TutorGuardrailDecision` correctly attributed while still costing
        exactly zero extra provider calls.
        """
        original_decision = self._evaluate_original(
            conversation_id=conversation_id, user_message=user_message, context=context,
            language=prepared_language.detected_language,
        )
        if original_decision.action == TutorGuardrailAction.REFUSE:
            return prepared_language, original_decision
        decision = self._decide_with_translation(
            conversation_id=conversation_id, user_message=user_message, context=context,
            preparation=prepared_language, original_decision=original_decision,
        )
        return prepared_language, decision

    async def _generate_validated_answer(
        self,
        *,
        question: str,
        recent_messages: list[TutorMessage],
        candidates: list[RetrievalCandidate],
        context: TutorContext,
        preparation: LanguageQueryPreparation,
    ) -> _ValidatedGeneration | None:
        """Generate, validate, and (for Hebrew) language-repair one answer.

        Returns `None` when the caller must fall back. Every model call
        lives here, strictly outside any Unit of Work (req. 5). The model
        is prompted with the learner's *original* question - never the
        translated query - and the citation validation the English path has
        always applied is re-run after the answer-language repair attempt
        too, so a repaired answer can never bypass it (req. 8).
        """
        prompt_request = self._prompt_builder.build(
            question=question, conversation_messages=recent_messages, candidates=candidates,
            context=context, language=preparation.detected_language,
        )

        model_result = await self._tutor_model.generate(prompt_request)
        grounding_status, issues = self._validate_output(model_result, candidates, context)
        if issues:
            model_result = await self._tutor_model.generate(prompt_request)
            grounding_status, issues = self._validate_output(model_result, candidates, context)

        if issues or grounding_status in (GroundingStatus.INVALID_CITATIONS, GroundingStatus.INSUFFICIENT_EVIDENCE):
            return None

        if not self._answer_language_matches(model_result.answer_markdown, preparation):
            # At most ONE bounded repair attempt, over the same approved
            # candidates and the same prompt - no new sources, no second
            # retrieval, no widened evidence.
            repair_request = self._build_answer_language_repair_request(prompt_request)
            model_result = await self._tutor_model.generate(repair_request)
            grounding_status, issues = self._validate_output(model_result, candidates, context)
            if issues or grounding_status in (
                GroundingStatus.INVALID_CITATIONS, GroundingStatus.INSUFFICIENT_EVIDENCE
            ):
                return None
            if not self._answer_language_matches(model_result.answer_markdown, preparation):
                # Never show a silent English answer to a Hebrew learner -
                # the exact localized fallback is the only remaining
                # acceptable outcome.
                return None
            return _ValidatedGeneration(
                model_result=model_result, grounding_status=grounding_status,
                prompt_version=repair_request.prompt_version,
            )

        return _ValidatedGeneration(
            model_result=model_result, grounding_status=grounding_status,
            prompt_version=prompt_request.prompt_version,
        )

    def _validate_output(
        self, model_result: TutorModelResult, candidates: list[RetrievalCandidate], context: TutorContext
    ) -> tuple[GroundingStatus, list[str]]:
        return self._guardrail.validate_output(
            answer_text=model_result.answer_markdown, cited_chunk_ids=model_result.cited_chunk_ids,
            retrieved_candidates=candidates, context=context,
        )

    def _answer_language_matches(self, answer_text: str, preparation: LanguageQueryPreparation) -> bool:
        """Phase G2E2A req. 8: a Hebrew answer instruction in the prompt is
        a request, not a guarantee.

        Only checked when the learner asked in Hebrew - an English request
        keeps its existing behavior exactly (this returns `True` without
        consulting the detector at all, so no English answer can newly be
        rejected by this phase). Uses the same shared detector every other
        consumer uses; never a second language classifier.
        """
        if not preparation.is_hebrew:
            return True
        return self._language_service.detect_language(answer_text) == DetectedLanguage.HE

    @staticmethod
    def _build_answer_language_repair_request(prompt_request: TutorModelRequest) -> TutorModelRequest:
        """The same request with one appended correction instruction -
        identically the same `retrieved_candidates`, `structured_context`,
        and `user_question`, so the repair attempt can never see a source
        the first attempt did not."""
        return prompt_request.model_copy(
            update={"system_instructions": prompt_request.system_instructions + _ANSWER_LANGUAGE_REPAIR_INSTRUCTION}
        )

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
        language: DetectedLanguage = DetectedLanguage.EN,
        retrieval_run_id: UUID | None,
    ) -> TutorResponse:
        fallback_text = self._language_service.localize(LocalizedMessageKey.INSUFFICIENT_EVIDENCE, language=language)
        answer = TutorAnswer(
            conversation_id=conversation.conversation_id,
            request_message_id=user_message.message_id,
            status=TutorAnswerStatus.FALLBACK,
            provider_type=self._tutor_model.provider_type,
            answer_markdown=fallback_text,
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
                content=fallback_text,
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
