"""Phase E1: the Knowledge Sufficiency Gate.

Deterministic, rule-based, no ML classifier and no network call - the
same auditability tradeoff already documented for
`guardrails.RuleBasedTutorGuardrail`. This gate runs *after* retrieval
and *before* prompt construction: it decides whether the retrieved
evidence is strong enough to send to a `TutorModelPort` at all, closing
the gap where a weak or unrelated (but non-empty) candidate list would
otherwise still reach the model.

`RuleBasedKnowledgeSufficiencyGate` is the real policy;
`DisabledKnowledgeSufficiencyGate` is the explicit, rollback-safe
implementation composed in whenever the feature flag is disabled (the
production default) - `GroundedAITutorService` calls exactly one
`KnowledgeSufficiencyGatePort.evaluate()` per `ask()`, for every
retrieval result including an empty candidate list, so the
enabled/disabled choice lives entirely in composition (which gate is
constructed), never as a scattered flag check or a separate
empty-candidate branch inside the service. `DisabledKnowledgeSufficiencyGate`
reproduces the service's pre-Phase-E1 behavior exactly: an empty
candidate list is still insufficient (`NO_CANDIDATES`), and a non-empty
list is always sufficient (`GATE_DISABLED`), regardless of score.
"""

from __future__ import annotations

import math
import re

from stock_research_core.application.ai_tutor.models import KnowledgeSufficiencyDecision, RetrievalCandidate, TutorContext

RULE_BASED_POLICY_VERSION = "knowledge-sufficiency-gate-v1"
DISABLED_POLICY_VERSION = "knowledge-sufficiency-gate-disabled-v1"

DEFAULT_MINIMUM_VECTOR_SCORE = 0.52
DEFAULT_MINIMUM_LEXICAL_SCORE = 0.05
DEFAULT_MINIMUM_CONTEXT_METADATA_SCORE = 0.90

REASON_CURRENT_INFORMATION_REQUEST = "CURRENT_INFORMATION_REQUEST"
REASON_NO_CANDIDATES = "NO_CANDIDATES"
REASON_VECTOR_SCORE_SUFFICIENT = "VECTOR_SCORE_SUFFICIENT"
REASON_LEXICAL_SCORE_SUFFICIENT = "LEXICAL_SCORE_SUFFICIENT"
REASON_METADATA_SCORE_SUFFICIENT = "METADATA_SCORE_SUFFICIENT"
REASON_BELOW_RELEVANCE_THRESHOLDS = "BELOW_RELEVANCE_THRESHOLDS"
REASON_GATE_DISABLED = "GATE_DISABLED"

# Stable, foundational finance terms that merely contain the word
# "current" as a modifier (e.g. "current ratio", "current yield") -
# checked first so they can never be misclassified as a live-information
# request just because of that one word.
_STABLE_FINANCE_TERMS = re.compile(r"\bcurrent (ratio|yield|assets|liabilities)\b", re.IGNORECASE)

# Explicit temporal signal words/phrases the spec calls out by name.
_TEMPORAL_KEYWORDS = re.compile(r"\b(today|currently|right now|as of|latest)\b", re.IGNORECASE)

# Nouns that name a value which changes over time (a live market price, a
# policy rate, a statutory limit/rule) - only treated as a live-information
# signal when paired with "current" or a specific year, never on their own.
_VOLATILE_FIGURE_TERMS = re.compile(
    r"\b(share price|stock price|exchange rate|interest rate|target (interest )?rate|"
    r"contribution limit|tax (rate|bracket|rule)s?|capital gains (rule|tax)s?)\b",
    re.IGNORECASE,
)
_CURRENT_WORD = re.compile(r"\bcurrent\b", re.IGNORECASE)
_YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")


def is_current_information_request(question: str) -> bool:
    """Conservative, deterministic classifier for "what's happening right
    now" questions the tutor's static, approved knowledge base can never
    answer - regardless of how well a chunk happens to score.

    Stable finance terminology that merely contains "current" (current
    ratio, current yield, ...) is excluded first so it is never
    misclassified.
    """
    if _STABLE_FINANCE_TERMS.search(question):
        return False
    if _TEMPORAL_KEYWORDS.search(question):
        return True
    if _CURRENT_WORD.search(question) and _VOLATILE_FIGURE_TERMS.search(question):
        return True
    if _YEAR_PATTERN.search(question) and _VOLATILE_FIGURE_TERMS.search(question):
        return True
    return False


def _validate_threshold(name: str, value: float, *, minimum: float | None, maximum: float | None) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value!r}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}, got {value!r}")


class RuleBasedKnowledgeSufficiencyGate:
    """Deterministic Knowledge Sufficiency Gate satisfying
    `KnowledgeSufficiencyGatePort`.

    Decision order (spec Phase E1):

    A. A current/live-information request is always insufficient,
       regardless of any candidate's score.
    B. An empty candidate list is always insufficient.
    C/D. Otherwise, sufficient when at least one of the best available
       vector/lexical/metadata scores meets its calibrated threshold
       (inclusive boundary - a score exactly at the threshold passes).
    E. Otherwise insufficient.
    """

    policy_version = RULE_BASED_POLICY_VERSION

    def __init__(
        self,
        *,
        minimum_vector_score: float = DEFAULT_MINIMUM_VECTOR_SCORE,
        minimum_lexical_score: float = DEFAULT_MINIMUM_LEXICAL_SCORE,
        minimum_context_metadata_score: float = DEFAULT_MINIMUM_CONTEXT_METADATA_SCORE,
    ) -> None:
        _validate_threshold("minimum_vector_score", minimum_vector_score, minimum=-1.0, maximum=1.0)
        _validate_threshold("minimum_lexical_score", minimum_lexical_score, minimum=0.0, maximum=None)
        _validate_threshold(
            "minimum_context_metadata_score", minimum_context_metadata_score, minimum=0.0, maximum=1.0
        )
        self._minimum_vector_score = minimum_vector_score
        self._minimum_lexical_score = minimum_lexical_score
        self._minimum_context_metadata_score = minimum_context_metadata_score

    def evaluate(
        self, *, query: str, candidates: list[RetrievalCandidate], context: TutorContext
    ) -> KnowledgeSufficiencyDecision:
        del context  # not consulted by this conservative rule set; kept for Protocol parity

        if is_current_information_request(query):
            return KnowledgeSufficiencyDecision(
                sufficient=False,
                reason_codes=[REASON_CURRENT_INFORMATION_REQUEST],
                best_vector_score=None,
                best_lexical_score=None,
                best_metadata_score=None,
                policy_version=self.policy_version,
            )

        if not candidates:
            return KnowledgeSufficiencyDecision(
                sufficient=False,
                reason_codes=[REASON_NO_CANDIDATES],
                best_vector_score=None,
                best_lexical_score=None,
                best_metadata_score=None,
                policy_version=self.policy_version,
            )

        vector_scores = [c.vector_score for c in candidates if c.vector_score is not None]
        lexical_scores = [c.lexical_score for c in candidates if c.lexical_score is not None]
        metadata_scores = [c.metadata_score for c in candidates]

        best_vector_score = max(vector_scores) if vector_scores else None
        best_lexical_score = max(lexical_scores) if lexical_scores else None
        best_metadata_score = max(metadata_scores) if metadata_scores else None

        vector_sufficient = best_vector_score is not None and best_vector_score >= self._minimum_vector_score
        lexical_sufficient = best_lexical_score is not None and best_lexical_score >= self._minimum_lexical_score
        metadata_sufficient = (
            best_metadata_score is not None and best_metadata_score >= self._minimum_context_metadata_score
        )

        reason_codes: list[str] = []
        if vector_sufficient:
            reason_codes.append(REASON_VECTOR_SCORE_SUFFICIENT)
        if lexical_sufficient:
            reason_codes.append(REASON_LEXICAL_SCORE_SUFFICIENT)
        if metadata_sufficient:
            reason_codes.append(REASON_METADATA_SCORE_SUFFICIENT)

        sufficient = bool(reason_codes)
        if not sufficient:
            reason_codes = [REASON_BELOW_RELEVANCE_THRESHOLDS]

        return KnowledgeSufficiencyDecision(
            sufficient=sufficient,
            reason_codes=reason_codes,
            best_vector_score=best_vector_score,
            best_lexical_score=best_lexical_score,
            best_metadata_score=best_metadata_score,
            policy_version=self.policy_version,
        )


class DisabledKnowledgeSufficiencyGate:
    """Explicit rollback-safe gate composed in whenever
    `TUTOR_KNOWLEDGE_SUFFICIENCY_GATE_ENABLED=false` (the default, and
    production's current value), so deploying this feature's code never
    by itself changes `GroundedAITutorService`'s pre-Phase-E1 behavior.

    Still evaluated exactly once per `ask()`, like every other gate -
    there is no separate empty-candidate branch in the service. It
    therefore reproduces the *legacy* rule directly: an empty candidate
    list is insufficient (`NO_CANDIDATES`, matching the fallback the
    service always ran on empty retrieval); any non-empty candidate list
    is unconditionally sufficient (`GATE_DISABLED`), regardless of score
    - exactly as every candidate list was handled before Phase E1.
    """

    policy_version = DISABLED_POLICY_VERSION

    def evaluate(
        self, *, query: str, candidates: list[RetrievalCandidate], context: TutorContext
    ) -> KnowledgeSufficiencyDecision:
        del query, context  # legacy rule only inspects whether candidates is empty

        if not candidates:
            return KnowledgeSufficiencyDecision(
                sufficient=False,
                reason_codes=[REASON_NO_CANDIDATES],
                best_vector_score=None,
                best_lexical_score=None,
                best_metadata_score=None,
                policy_version=self.policy_version,
            )

        return KnowledgeSufficiencyDecision(
            sufficient=True,
            reason_codes=[REASON_GATE_DISABLED],
            best_vector_score=None,
            best_lexical_score=None,
            best_metadata_score=None,
            policy_version=self.policy_version,
        )
