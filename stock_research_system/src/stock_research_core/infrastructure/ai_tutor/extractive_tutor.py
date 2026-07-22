"""Deterministic extractive tutor provider, satisfying `TutorModelPort`.

No LLM, no external API, no randomness: selects the most
query-relevant sentence from each of the highest-ranked retrieved
chunks (already ranked by the retriever) using deterministic
lowercase-token overlap, and assembles a concise, cited answer from
them. This is the cost-conscious, always-available "Mode A" provider
described in the spec ss19/ss3 - the safe default when no external
model is configured.

Known limitations (documented per spec ss19):
- Reliable and inexpensive, but not conversational: it extracts
  existing sentences rather than synthesizing new prose.
- Token-overlap relevance is a simple heuristic, not semantic
  understanding - it can miss paraphrased matches a real LLM would
  catch, and is deliberately not "smarter" than that trade-off allows.
"""

from __future__ import annotations

import re

from stock_research_core.application.ai_tutor.models import TutorModelRequest, TutorModelResult
from stock_research_core.domain.ai_tutor.enums import TutorProviderType
from stock_research_core.domain.ai_tutor.models import EXACT_INSUFFICIENT_EVIDENCE_FALLBACK

MODEL_NAME = "extractive-tutor-v1"

_MAX_CITATIONS = 3
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
_WORD_PATTERN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "of", "to", "in", "on", "for", "and", "or", "but", "with", "at", "by",
        "what", "how", "why", "does", "do", "did", "which", "that", "this",
        "these", "those", "it", "its", "can", "could", "should", "would",
        "i", "my", "you", "your", "we", "our", "as", "if", "than", "then",
    }
)


def _tokenize(text: str) -> set[str]:
    return {word for word in _WORD_PATTERN.findall(text.lower()) if word not in _STOPWORDS and len(word) > 1}


def _split_sentences(content: str) -> list[str]:
    return [sentence.strip() for sentence in _SENTENCE_SPLIT_PATTERN.split(content) if sentence.strip()]


def _best_sentence(content: str, question_tokens: set[str]) -> tuple[str | None, int]:
    best_sentence: str | None = None
    best_score = -1
    for sentence in _split_sentences(content):
        score = len(_tokenize(sentence) & question_tokens)
        if score > best_score:
            best_score = score
            best_sentence = sentence
    return best_sentence, best_score


def _insufficient_evidence_result() -> TutorModelResult:
    return TutorModelResult(
        answer_markdown=EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
        cited_chunk_ids=[],
        provider_type=TutorProviderType.EXTRACTIVE,
        model_name=MODEL_NAME,
        model_response_id=None,
    )


class DeterministicExtractiveTutor:
    """Deterministic, LLM-free tutor provider satisfying `TutorModelPort`."""

    model_name = MODEL_NAME
    provider_type = TutorProviderType.EXTRACTIVE

    async def generate(self, request: TutorModelRequest) -> TutorModelResult:
        if not request.retrieved_candidates:
            return _insufficient_evidence_result()

        question_tokens = _tokenize(request.user_question)
        selections: list[tuple[int, str, int]] = []
        for index, candidate in enumerate(request.retrieved_candidates):
            sentence, score = _best_sentence(candidate.chunk.content, question_tokens)
            if sentence is not None and score > 0:
                selections.append((index, sentence, score))

        if not selections:
            return _insufficient_evidence_result()

        selections.sort(key=lambda item: (-item[2], item[0]))
        top_selections = sorted(selections[:_MAX_CITATIONS], key=lambda item: item[0])

        answer_lines: list[str] = []
        cited_chunk_ids = []
        for citation_number, (index, sentence, _score) in enumerate(top_selections, start=1):
            answer_lines.append(f"{sentence} [{citation_number}]")
            cited_chunk_ids.append(request.retrieved_candidates[index].chunk.chunk_id)

        return TutorModelResult(
            answer_markdown=" ".join(answer_lines),
            cited_chunk_ids=cited_chunk_ids,
            provider_type=TutorProviderType.EXTRACTIVE,
            model_name=MODEL_NAME,
            model_response_id=None,
        )
