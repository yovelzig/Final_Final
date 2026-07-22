"""Deterministic rule-based guardrail policy for the grounded AI tutor.

Keyword/regex rules only - no ML classifier, no external call, no
randomness. This is the structural line that keeps the tutor from
becoming a source of stock predictions or personalized investment
advice: `evaluate_input` classifies every learner message before any
retrieval or generation happens, and `validate_output` re-checks the
model's own answer text before it is ever shown to a learner.

Known limitation (documented per spec ss19/ss17): keyword/regex matching
is not full NLU. It is deliberately conservative for REFUSE-worthy
categories (buy/sell instructions, guaranteed-return claims) and can
both under- and over-match phrasing outside the patterns below - that
tradeoff is intentional for a deterministic, auditable safety layer.
"""

from __future__ import annotations

import re
from uuid import UUID

from stock_research_core.application.ai_tutor.models import RetrievalCandidate, TutorContext
from stock_research_core.domain.ai_tutor.enums import (
    GroundingStatus,
    TutorContextType,
    TutorGuardrailAction,
    TutorRequestCategory,
)
from stock_research_core.domain.ai_tutor.models import (
    EXACT_ADVICE_REFUSAL,
    EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
    EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL,
    TutorGuardrailDecision,
    TutorMessage,
)

GUARDRAIL_POLICY_VERSION = "tutor-guardrail-v1"

_EDUCATIONAL_BOUNDARY_SUFFIX = (
    " I can walk through the relevant concepts - such as diversification, risk tolerance, "
    "time horizon, and expected volatility - that generally apply to that kind of decision."
)

_GUARANTEED_RETURN_ROOT = re.compile(r"\bguarante\w*\b", re.IGNORECASE)
_GUARANTEED_RETURN_OUTCOME = re.compile(
    r"\b(return|returns|profit|profits|gain|gains|money|percent)\b|\d+\s*%", re.IGNORECASE
)
_GUARANTEED_RETURN_PHRASES = (
    re.compile(r"\bcan'?t lose\b", re.IGNORECASE),
    re.compile(r"\bcannot lose\b", re.IGNORECASE),
    re.compile(r"\bnever lose\b", re.IGNORECASE),
    re.compile(r"\bsure (thing|bet|win)\b", re.IGNORECASE),
    re.compile(r"\brisk[- ]free\b.*\b(return|returns|profit)\b", re.IGNORECASE),
    re.compile(r"\bwhich strategy (cannot|can'?t) lose\b", re.IGNORECASE),
)

_BUY_SELL_PHRASES = (
    re.compile(r"\bshould i (buy|sell|invest in)\b", re.IGNORECASE),
    re.compile(r"\bwhat should i (buy|sell)\b", re.IGNORECASE),
    re.compile(r"\bwhich (stock|security|etf|fund)s? (should i |do i |to )?(buy|sell)\b", re.IGNORECASE),
    re.compile(r"\btell me (which|what) (stock|security|etf|fund) to (buy|sell)\b", re.IGNORECASE),
    re.compile(r"\bis (this|it|now) a good (entry|exit) (price|point|time)\b", re.IGNORECASE),
    re.compile(r"\b(buy|sell) (nvda|aapl|tsla|msft|amzn|googl|goog|meta|spy|qqq)\b", re.IGNORECASE),
    re.compile(r"\bshould i (buy|sell)\b", re.IGNORECASE),
    re.compile(r"\b(buy|sell) my\b", re.IGNORECASE),
    re.compile(r"\b(buy|sell)\b[\w\s]{0,20}\bposition\b", re.IGNORECASE),
)

_SCENARIO_FUTURE_QUESTION_PHRASES = (
    re.compile(r"\bwhat happens next\b", re.IGNORECASE),
    re.compile(
        r"\bdoes (it|the stock|the price|the market) (go up|go down|rise|fall|rally|crash|drop)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bwhich option is correct\b", re.IGNORECASE),
    re.compile(r"\bwhat('?s| is) the (outcome|answer|right (choice|option))\b", re.IGNORECASE),
    re.compile(r"\bdid (it|the stock|the trade) work out\b", re.IGNORECASE),
    re.compile(r"\bwhat (will|would) happen\b", re.IGNORECASE),
    re.compile(r"\bhow does (it|this|the scenario) (turn out|end)\b", re.IGNORECASE),
)

_PERSONALIZED_ALLOCATION_PHRASES = (
    re.compile(r"\bhow should i invest\b", re.IGNORECASE),
    re.compile(r"\bwhat (percentage|percent|%) should i (put|invest|allocate)\b", re.IGNORECASE),
    re.compile(r"\bhow (much|many) should i (invest|put|allocate)\b", re.IGNORECASE),
    re.compile(r"\ballocate my (money|cash|savings|portfolio)\b", re.IGNORECASE),
    re.compile(r"\bwhere should i (put|invest) my money\b", re.IGNORECASE),
    re.compile(r"\bhow should i invest my\b", re.IGNORECASE),
)

_FINANCE_EDUCATION_VOCABULARY = frozenset(
    {
        "invest", "investing", "investment", "investor", "stock", "stocks", "share", "shares",
        "bond", "bonds", "etf", "etfs", "fund", "funds", "market", "markets", "portfolio",
        "diversif", "diversification", "diversify", "risk", "risks", "return", "returns",
        "price", "prices", "volatility", "drawdown", "benchmark", "index", "indexes",
        "indices", "interest", "inflation", "compound", "compounding", "dividend", "dividends",
        "lesson", "lessons", "exercise", "exercises", "scenario", "scenarios", "skill",
        "skills", "learn", "learning", "concept", "concepts", "finance", "financial",
        "economy", "economic", "asset", "assets", "allocation", "concentration", "hhi",
        "turnover", "capital", "equity", "equities", "cash", "currency", "trade", "trading",
        "transaction", "valuation", "decision", "outcome", "hedge", "hedging", "liquidity",
        "yield", "rate", "rates", "portfolio", "sector", "sectors", "security", "securities",
    }
)


def _matches_any(text: str, patterns: tuple[re.Pattern[str], ...]) -> str | None:
    for pattern in patterns:
        if pattern.search(text):
            return pattern.pattern
    return None


_FINANCE_EDUCATION_STEMS = ("diversif", "invest", "portfol", "financ")


def _is_off_topic(text: str) -> bool:
    tokens = re.findall(r"[a-z]+", text.lower())
    if any(token in _FINANCE_EDUCATION_VOCABULARY for token in tokens):
        return False
    if any(token.startswith(_FINANCE_EDUCATION_STEMS) for token in tokens):
        return False
    return True


class RuleBasedTutorGuardrail:
    """Deterministic keyword/regex guardrail satisfying `TutorGuardrailPort`."""

    policy_version = GUARDRAIL_POLICY_VERSION

    def evaluate_input(
        self, *, conversation_id: UUID, message: TutorMessage, context: TutorContext
    ) -> TutorGuardrailDecision:
        text = message.content

        if context.context_type == TutorContextType.SCENARIO_BEFORE_DECISION and _matches_any(
            text, _SCENARIO_FUTURE_QUESTION_PHRASES
        ):
            return TutorGuardrailDecision(
                conversation_id=conversation_id,
                message_id=message.message_id,
                request_category=TutorRequestCategory.UNSUPPORTED_TOPIC,
                action=TutorGuardrailAction.REFUSE,
                matched_rule_codes=["SCENARIO_FUTURE_INFORMATION_REQUEST"],
                safe_response_override=EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL,
                policy_version=self.policy_version,
            )

        if _matches_any(text, _GUARANTEED_RETURN_PHRASES) or (
            _GUARANTEED_RETURN_ROOT.search(text) and _GUARANTEED_RETURN_OUTCOME.search(text)
        ):
            return TutorGuardrailDecision(
                conversation_id=conversation_id,
                message_id=message.message_id,
                request_category=TutorRequestCategory.GUARANTEED_RETURN_REQUEST,
                action=TutorGuardrailAction.REFUSE,
                matched_rule_codes=["GUARANTEED_RETURN"],
                safe_response_override=EXACT_ADVICE_REFUSAL,
                policy_version=self.policy_version,
            )

        if _matches_any(text, _BUY_SELL_PHRASES):
            return TutorGuardrailDecision(
                conversation_id=conversation_id,
                message_id=message.message_id,
                request_category=TutorRequestCategory.BUY_SELL_REQUEST,
                action=TutorGuardrailAction.REFUSE,
                matched_rule_codes=["BUY_SELL_INSTRUCTION"],
                safe_response_override=EXACT_ADVICE_REFUSAL,
                policy_version=self.policy_version,
            )

        if _matches_any(text, _PERSONALIZED_ALLOCATION_PHRASES):
            return TutorGuardrailDecision(
                conversation_id=conversation_id,
                message_id=message.message_id,
                request_category=TutorRequestCategory.PERSONALIZED_INVESTMENT_ADVICE,
                action=TutorGuardrailAction.ALLOW_WITH_BOUNDARY,
                matched_rule_codes=["PERSONALIZED_ALLOCATION"],
                safe_response_override=EXACT_ADVICE_REFUSAL + _EDUCATIONAL_BOUNDARY_SUFFIX,
                policy_version=self.policy_version,
            )

        if _is_off_topic(text):
            return TutorGuardrailDecision(
                conversation_id=conversation_id,
                message_id=message.message_id,
                request_category=TutorRequestCategory.UNSUPPORTED_TOPIC,
                action=TutorGuardrailAction.FALLBACK,
                matched_rule_codes=["OFF_TOPIC"],
                safe_response_override=EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
                policy_version=self.policy_version,
            )

        return TutorGuardrailDecision(
            conversation_id=conversation_id,
            message_id=message.message_id,
            request_category=TutorRequestCategory.ALLOWED_EDUCATION,
            action=TutorGuardrailAction.ALLOW,
            matched_rule_codes=[],
            safe_response_override=None,
            policy_version=self.policy_version,
        )

    def validate_output(
        self,
        *,
        answer_text: str,
        cited_chunk_ids: list[UUID],
        retrieved_candidates: list[RetrievalCandidate],
        context: TutorContext,
    ) -> tuple[GroundingStatus, list[str]]:
        issues: list[str] = []

        retrieved_ids = {candidate.chunk.chunk_id for candidate in retrieved_candidates}
        invalid_citations = [chunk_id for chunk_id in cited_chunk_ids if chunk_id not in retrieved_ids]
        if invalid_citations:
            issues.append("INVALID_CITATION_CHUNK_ID")

        if _matches_any(answer_text, _GUARANTEED_RETURN_PHRASES) or (
            _GUARANTEED_RETURN_ROOT.search(answer_text) and _GUARANTEED_RETURN_OUTCOME.search(answer_text)
        ):
            issues.append("GUARANTEED_RETURN_CLAIM")

        if _matches_any(answer_text, _BUY_SELL_PHRASES) or re.search(
            r"\b(buy|sell) (it|this|that|now|\d)", answer_text, re.IGNORECASE
        ):
            issues.append("DIRECT_BUY_SELL_INSTRUCTION")

        if context.context_type == TutorContextType.SCENARIO_BEFORE_DECISION and re.search(
            r"\b(the (stock|price|market) (rose|fell|rallied|crashed|dropped)|the (correct|right) option "
            r"(is|was)|the outcome (is|was)|afterward|in hindsight|it turned out)\b",
            answer_text,
            re.IGNORECASE,
        ):
            issues.append("SCENARIO_FUTURE_INFORMATION_LEAK")

        if context.context_type == TutorContextType.PORTFOLIO_EXPLANATION and re.search(
            r"\b(sell|buy) \d+(\.\d+)? shares?\b|\ballocate \d+(\.\d+)?%\b|\breplace this stock\b",
            answer_text,
            re.IGNORECASE,
        ):
            issues.append("PORTFOLIO_TRADE_PRESCRIPTION")

        allowed_urls = {
            candidate.source.canonical_url
            for candidate in retrieved_candidates
            if candidate.source.canonical_url
        }
        for url in re.findall(r"https?://\S+", answer_text):
            if url.rstrip(".,)") not in allowed_urls:
                issues.append("UNVERIFIED_URL")
                break

        if re.search(r"<thinking>|chain[- ]of[- ]thought|hidden reasoning", answer_text, re.IGNORECASE):
            issues.append("HIDDEN_REASONING_MARKER")

        if invalid_citations:
            status = GroundingStatus.INVALID_CITATIONS
        elif not cited_chunk_ids and answer_text not in (
            EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
            EXACT_ADVICE_REFUSAL,
        ):
            status = GroundingStatus.INSUFFICIENT_EVIDENCE
        elif issues:
            status = GroundingStatus.PARTIALLY_GROUNDED
        else:
            status = GroundingStatus.GROUNDED

        return status, issues
