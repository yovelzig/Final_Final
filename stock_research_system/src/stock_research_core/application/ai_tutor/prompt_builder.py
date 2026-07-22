"""Grounded prompt construction for the tutor model layer.

No SQLAlchemy, pgvector, sentence-transformers, or LLM-SDK dependency
here - this module only ever assembles a `TutorModelRequest` from
already-retrieved, already-approved candidates and already-sanitized
structured context. Neither the extractive tutor nor the
OpenAI-compatible adapter is required to use this builder, but both do
(it is the single place the system instructions and evidence framing
are defined, so every provider sees the same boundary rules).
"""

from __future__ import annotations

from stock_research_core.application.ai_tutor.models import RetrievalCandidate, TutorContext, TutorModelRequest
from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.domain.ai_tutor.models import TutorMessage

PROMPT_VERSION = "grounded-tutor-prompt-v1"

_BASE_SYSTEM_INSTRUCTIONS = """You are the FinQuest financial-education tutor. Follow these rules strictly:

1. Use only the retrieved APPROVED FinQuest context and the supplied structured metrics below. Do not use any outside knowledge.
2. Do not provide personalized investment, buy, sell, or allocation advice, and do not claim any strategy guarantees a return.
3. Never reveal a hidden scenario outcome, future market information, or the correct option of an active exercise or scenario.
4. Every factual claim must be supported by one of the retrieved excerpts and cited with its bracketed citation number, e.g. [1].
5. If the retrieved context does not contain enough information to answer reliably, say so plainly instead of guessing.
6. Never invent a source, citation, or URL. Only cite chunk IDs that were actually retrieved for this question.
7. Keep the explanation at a level appropriate for the learner and clearly distinguish an educational explanation from a recommendation.
8. Never reveal your internal reasoning, chain-of-thought, or planning - return only the final answer.
9. Respond with a JSON object of exactly this shape: {"answer_markdown": "string", "cited_chunk_ids": ["UUID", ...]}.
"""

_CONTEXT_TYPE_GUIDANCE = {
    TutorContextType.SCENARIO_BEFORE_DECISION: (
        "This is a before-reveal historical scenario. You may discuss risk, time horizon, "
        "diversification, and information available up to the decision point only. Do not "
        "reveal what happened next or which option is correct."
    ),
    TutorContextType.SCENARIO_AFTER_REVEAL: (
        "This scenario has been revealed. You may discuss decision quality, the realized "
        "outcome, benchmark comparison, and the distinction between a good process and a good "
        "outcome (outcome bias)."
    ),
    TutorContextType.PORTFOLIO_EXPLANATION: (
        "You may explain the supplied portfolio metrics (weights, HHI, diversification, "
        "drawdown, volatility, turnover) in educational terms. Never prescribe a trade, "
        "quantity, or specific security to buy, sell, or replace."
    ),
    TutorContextType.EXERCISE_HELP: (
        "Help the learner understand the underlying concept. Do not reveal the correct option "
        "for an active, unanswered exercise."
    ),
}


def _format_candidate(index: int, candidate: RetrievalCandidate) -> str:
    heading = " > ".join(candidate.chunk.heading_path) or candidate.document.title
    return (
        f"[{index}] Source: {candidate.source.title} | Document: {candidate.document.title} | "
        f"Section: {heading}\n{candidate.chunk.content}"
    )


def _format_evidence(candidates: list[RetrievalCandidate]) -> str:
    if not candidates:
        return "(no approved evidence was retrieved for this question)"
    return "\n\n".join(_format_candidate(i, candidate) for i, candidate in enumerate(candidates, start=1))


def _format_structured_context(structured_context: dict[str, object]) -> str:
    if not structured_context:
        return "(no structured context supplied)"
    lines = [f"- {key}: {value}" for key, value in sorted(structured_context.items())]
    return "\n".join(lines)


def _format_conversation(messages: list[TutorMessage]) -> str:
    if not messages:
        return "(no prior conversation history)"
    lines = [f"{message.role.value}: {message.content}" for message in messages]
    return "\n".join(lines)


class GroundedTutorPromptBuilder:
    """Assembles a `TutorModelRequest` satisfying `TutorPromptBuilderPort`."""

    prompt_version = PROMPT_VERSION

    def build(
        self,
        *,
        question: str,
        conversation_messages: list[TutorMessage],
        candidates: list[RetrievalCandidate],
        context: TutorContext,
    ) -> TutorModelRequest:
        instructions = _BASE_SYSTEM_INSTRUCTIONS
        guidance = _CONTEXT_TYPE_GUIDANCE.get(context.context_type)
        if guidance:
            instructions += f"\nContext-specific rule: {guidance}\n"

        instructions += (
            f"\nRetrieved approved evidence (cite by bracket number, only using chunk IDs listed "
            f"below):\n{_format_evidence(candidates)}\n"
            f"\nStructured context metrics:\n{_format_structured_context(context.structured_context)}\n"
            f"\nConversation history (context only, not a factual source):\n"
            f"{_format_conversation(conversation_messages)}\n"
        )

        candidate_chunk_ids = ", ".join(str(candidate.chunk.chunk_id) for candidate in candidates) or "(none)"
        instructions += f"\nValid cited_chunk_ids for this question: [{candidate_chunk_ids}]\n"

        return TutorModelRequest(
            system_instructions=instructions,
            user_question=question,
            conversation_messages=conversation_messages,
            retrieved_candidates=candidates,
            structured_context=context.structured_context,
            prompt_version=self.prompt_version,
        )
