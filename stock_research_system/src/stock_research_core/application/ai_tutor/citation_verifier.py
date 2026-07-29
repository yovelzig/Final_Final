"""`TutorCitationVerifier`: the Tutor knowledge-base citation/URL checks,
extracted verbatim from `RuleBasedTutorGuardrail.validate_output` (spec
G2D2 section 17) - kept strictly behavior-identical (same two checks,
same issue codes, same order) and only organizationally separated from
the guardrail's other output-safety checks (guaranteed-return claims,
buy/sell instructions, scenario/portfolio leaks, hidden-reasoning
markers), which remain inline in `guardrails.py`.

Deliberately a distinct class from `live_research.citation_verifier.
ResearchEvidenceCitationVerifier` - Tutor citations are chunk IDs from
`KnowledgeRetrieverPort` candidates; Live Research citations are
`EvidenceItem` IDs from a verified `ResearchRun`. The two must never be
interchangeable.
"""

from __future__ import annotations

import re
from uuid import UUID

from stock_research_core.application.ai_tutor.models import RetrievalCandidate

_URL_PATTERN = re.compile(r"https?://\S+")


class TutorCitationVerifier:
    """Two separate methods, not one combined `verify()` - `guardrails.
    RuleBasedTutorGuardrail.validate_output` calls each at its own
    original position among the guardrail's other output-safety checks,
    so the returned `issues` list's order is unchanged by this
    extraction."""

    def check_citations(self, *, cited_chunk_ids: list[UUID], retrieved_candidates: list[RetrievalCandidate]) -> list[str]:
        retrieved_ids = {candidate.chunk.chunk_id for candidate in retrieved_candidates}
        invalid_citations = [chunk_id for chunk_id in cited_chunk_ids if chunk_id not in retrieved_ids]
        return ["INVALID_CITATION_CHUNK_ID"] if invalid_citations else []

    def check_urls(self, *, answer_text: str, retrieved_candidates: list[RetrievalCandidate]) -> list[str]:
        allowed_urls = {
            candidate.source.canonical_url for candidate in retrieved_candidates if candidate.source.canonical_url
        }
        for url in _URL_PATTERN.findall(answer_text):
            if url.rstrip(".,)") not in allowed_urls:
                return ["UNVERIFIED_URL"]
        return []
