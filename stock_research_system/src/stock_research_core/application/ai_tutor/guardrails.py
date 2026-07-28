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

Phase G2E2A: `evaluate_input` gained two optional keyword-only
parameters. `language` selects which exact, approved string
(`application.language.localization.localize`) is used for
`safe_response_override` - it never changes which regex rule matches;
matching always runs against `message.content` exactly as given
(English, Hebrew, or a bounded English translation - whatever the
caller passes). `apply_topic_vocabulary_check` gates the off-topic
check specifically: `_is_off_topic`'s vocabulary is English-only, so it
has no signal at all for Hebrew-script text (zero `[a-z]` tokens is "no
data," not "off-topic evidence") - callers evaluating a Hebrew
question's *original* text pass `apply_topic_vocabulary_check=False`
and rely on the Knowledge Sufficiency Gate (over the translated
retrieval query) as the real topic-relevance filter instead; the
REFUSE-worthy safety categories above it are never skipped.

Phase G2E2A correction pass (req. 4): each of the four safety
categories now carries a Hebrew-script pattern group beside its English
one, so a *pure* Hebrew request with no embedded English trigger word
(no "buy"/"sell"/"guarantee") is classified from the learner's own words
alone - never only from a translation that might fail. The Hebrew groups
can never match Latin-script text, so English behavior is byte-identical
to before. `more_restrictive_action` exposes the single restrictiveness
ordering both `GroundedAITutorService` and the LangGraph coach use to
merge an original-text decision with a translated-text decision: the
merge can only escalate toward REFUSE, never downgrade.
"""

from __future__ import annotations

import re
from uuid import UUID

from stock_research_core.application.ai_tutor.models import RetrievalCandidate, TutorContext
from stock_research_core.application.language.enums import DetectedLanguage, LocalizedMessageKey
from stock_research_core.application.language.localization import localize
from stock_research_core.domain.ai_tutor.enums import (
    GroundingStatus,
    TutorContextType,
    TutorGuardrailAction,
    TutorRequestCategory,
)
from stock_research_core.domain.ai_tutor.models import (
    APPROVED_INSUFFICIENT_EVIDENCE_FALLBACKS,
    EXACT_ADVICE_REFUSAL,
    EXACT_ADVICE_REFUSAL_HE,
    TutorGuardrailDecision,
    TutorMessage,
)

GUARDRAIL_POLICY_VERSION = "tutor-guardrail-v1"

_EDUCATIONAL_BOUNDARY_SUFFIX = (
    " I can walk through the relevant concepts - such as diversification, risk tolerance, "
    "time horizon, and expected volatility - that generally apply to that kind of decision."
)
_EDUCATIONAL_BOUNDARY_SUFFIX_HE = (
    " אני יכול לעבור איתך על המושגים הרלוונטיים - כגון פיזור סיכונים, סיבולת סיכון, אופק "
    "זמן ותנודתיות צפויה - שרלוונטיים בדרך כלל להחלטה מסוג זה."
)

#: Every exact string `validate_output` treats as an already-approved,
#: non-cited answer (never flagged `INSUFFICIENT_EVIDENCE` for lacking a
#: citation) - the English and Hebrew fallback and advice-refusal texts.
_APPROVED_NON_CITED_TEXTS = APPROVED_INSUFFICIENT_EVIDENCE_FALLBACKS | {
    EXACT_ADVICE_REFUSAL,
    EXACT_ADVICE_REFUSAL_HE,
}


def _boundary_suffix(language: DetectedLanguage) -> str:
    return _EDUCATIONAL_BOUNDARY_SUFFIX_HE if language == DetectedLanguage.HE else _EDUCATIONAL_BOUNDARY_SUFFIX

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

# -- Hebrew-script safety patterns (Phase G2E2A req. 4) --------------------
#
# Deliberately Hebrew-only: `\b` word boundaries are omitted (Hebrew
# words take inseparable ל/ב/ה/ו/מ/ש prefixes, so a boundary anchor
# would reject exactly the common forms), and `[^?]{0,N}` gaps keep every
# pattern bounded and inside a single question. None of these can match
# Latin-script text, so an English question's classification is
# byte-identical to before this phase.

#: ב.ט.ח ("promise"/"guarantee") forms, paired with an outcome noun -
#: mirroring the English root+outcome rule rather than refusing on the
#: verb alone ("אני מבטיח לחזור על זה" is not a guaranteed-return claim).
_HEBREW_GUARANTEE_ROOT = re.compile(r"(תבטיח|תבטיחי|תבטיחו|מבטיח|מבטיחה|להבטיח|הבטחה|מובטח|מובטחת|אבטיח)")
_HEBREW_GUARANTEE_OUTCOME = re.compile(r"(תשואה|תשואות|רווח|רווחים|הפסד|כסף|אחוז|אחוזים)|\d+\s*%")
_HEBREW_GUARANTEED_RETURN_PHRASES = (
    re.compile(r"(בלי|ללא|חסר|חסרת)\s+סיכון"),
    re.compile(r"בטוח\s+ש?(אני\s+)?(ארוויח|תרוויח|נרוויח|מרוויחים)"),
    re.compile(r"(אי\s+אפשר|אפשר\s+לא|בלי)\s+להפסיד"),
    re.compile(r"(עסקה|השקעה|אסטרטגיה)\s+(בטוחה|מובטחת)"),
)

_HEBREW_BUY_SELL_PHRASES = (
    re.compile(r"(איזו|איזה|אילו)\s+(מניה|מניות|נייר|ניירות|קרן|קרנות|תעודה|אגח)[^?]{0,40}(לקנות|למכור)"),
    re.compile(r"כדאי\s+(לי\s+)?(לקנות|למכור|להשקיע\s+ב)"),
    re.compile(r"(האם|אם)\s+(כדאי\s+)?(לקנות|למכור)"),
    re.compile(r"(תגיד|תמליץ|תמליצי|המלץ|תבחר)\s+לי[^?]{0,30}(לקנות|למכור)"),
    re.compile(r"מה\s+(כדאי\s+)?(לי\s+)?(לקנות|למכור)"),
    re.compile(r"(לקנות|למכור)\s+(עכשיו|היום|מיד|כרגע)"),
    re.compile(r"(מניה|מניות)\s+(כדאי|מומלצת|מומלצות)"),
)

_HEBREW_SCENARIO_FUTURE_QUESTION_PHRASES = (
    re.compile(r"מה\s+(קורה|קרה|יקרה)\s+(בהמשך|אחר\s*כך|אחרי|בסוף|הלאה)"),
    re.compile(r"(תגלה|גלה|תגלי|תספר|ספר)\s+לי[^?]{0,30}(קורה|קרה|יקרה|התוצאה|הסוף)"),
    re.compile(r"מה\s+(התוצאה|הסוף|התשובה\s+הנכונה|הפתרון\s+הנכון)"),
    re.compile(r"(איזו|איזה)\s+(אפשרות|תשובה|בחירה|החלטה)\s+(נכונה|הנכונה|נכון|הנכון)"),
    re.compile(r"(המניה|המחיר|השוק)\s+(עלה|עלתה|ירד|ירדה|יעלה|תעלה|ירדו|תרד|קרס|התרסק)"),
    re.compile(r"איך\s+(התרחיש|זה|הסיפור)\s+(נגמר|מסתיים|נגמרה)"),
)

_HEBREW_PERSONALIZED_ALLOCATION_PHRASES = (
    re.compile(r"כמה\s+(מ)?(ה)?(כסף|כספי|חסכונות|חסכון|תיק|סכום|הון)[^?]{0,30}(להשקיע|לשים|להקצות|לחלק)"),
    re.compile(r"כמה\s+(אחוז|אחוזים|כסף|מהתיק)[^?]{0,30}(להשקיע|לשים|להקצות)"),
    re.compile(r"איך\s+(להשקיע|לחלק|להקצות)\s+(את\s+)?(ה)?(כסף|כספי|תיק|התיק|חסכונות|החסכונות)"),
    re.compile(r"(להקצות|לחלק)\s+(את\s+)?(ה)?(כסף|תיק|התיק|חסכונות|החסכונות)\s+שלי"),
    re.compile(r"איפה\s+(להשקיע|לשים)\s+(את\s+)?(ה)?כסף\s+שלי"),
)

#: Hebrew counterparts of `validate_output`'s scenario-outcome leak
#: check - a Hebrew answer must not reveal how a
#: `SCENARIO_BEFORE_DECISION` scenario turned out either.
_HEBREW_SCENARIO_OUTCOME_LEAK_PHRASES = (
    re.compile(r"(המניה|המחיר|השוק)\s+(עלה|עלתה|ירד|ירדה|קרס|התרסק|זינק|זינקה)"),
    re.compile(r"(האפשרות|התשובה|הבחירה)\s+(הנכונה|הנכון)\s+(היא|הייתה|הינה)"),
    re.compile(r"(התוצאה|הסוף)\s+(היה|הייתה|היא)"),
    re.compile(r"(בדיעבד|בהמשך\s+התרחיש|לאחר\s+מכן\s+התברר|התברר\s+ש)"),
)

_ALL_GUARANTEED_RETURN_PHRASES = _GUARANTEED_RETURN_PHRASES + _HEBREW_GUARANTEED_RETURN_PHRASES
_ALL_BUY_SELL_PHRASES = _BUY_SELL_PHRASES + _HEBREW_BUY_SELL_PHRASES
_ALL_SCENARIO_FUTURE_QUESTION_PHRASES = (
    _SCENARIO_FUTURE_QUESTION_PHRASES + _HEBREW_SCENARIO_FUTURE_QUESTION_PHRASES
)
_ALL_PERSONALIZED_ALLOCATION_PHRASES = (
    _PERSONALIZED_ALLOCATION_PHRASES + _HEBREW_PERSONALIZED_ALLOCATION_PHRASES
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


def _claims_guaranteed_return(text: str) -> bool:
    """English root+outcome rule, its fixed English phrase list, and the
    Hebrew equivalents of both - one predicate so `evaluate_input` and
    `validate_output` can never drift apart on this category."""
    if _matches_any(text, _ALL_GUARANTEED_RETURN_PHRASES):
        return True
    if _GUARANTEED_RETURN_ROOT.search(text) and _GUARANTEED_RETURN_OUTCOME.search(text):
        return True
    return bool(_HEBREW_GUARANTEE_ROOT.search(text) and _HEBREW_GUARANTEE_OUTCOME.search(text))


#: The single restrictiveness ordering used to merge two decisions about
#: the same request (Phase G2E2A: a learner's original-language text and
#: a bounded English translation of it). Higher always wins.
_ACTION_RESTRICTIVENESS: dict[TutorGuardrailAction, int] = {
    TutorGuardrailAction.ALLOW: 0,
    TutorGuardrailAction.ALLOW_WITH_BOUNDARY: 1,
    TutorGuardrailAction.FALLBACK: 2,
    TutorGuardrailAction.REFUSE: 3,
}


def more_restrictive_decision(
    primary: TutorGuardrailDecision, secondary: TutorGuardrailDecision
) -> TutorGuardrailDecision:
    """The more restrictive of two decisions about the same request,
    preferring `primary` on a tie.

    Phase G2E2A req. 4/11: `primary` is always the decision made on the
    learner's *original* words, so a translated-text decision can only
    escalate toward REFUSE - an original REFUSE is never downgraded, and
    a translation can never talk the guardrail out of a decision the real
    question already earned.
    """
    if _ACTION_RESTRICTIVENESS[secondary.action] > _ACTION_RESTRICTIVENESS[primary.action]:
        return secondary
    return primary


class RuleBasedTutorGuardrail:
    """Deterministic keyword/regex guardrail satisfying `TutorGuardrailPort`."""

    policy_version = GUARDRAIL_POLICY_VERSION

    def evaluate_input(
        self,
        *,
        conversation_id: UUID,
        message: TutorMessage,
        context: TutorContext,
        language: DetectedLanguage = DetectedLanguage.EN,
        apply_topic_vocabulary_check: bool = True,
    ) -> TutorGuardrailDecision:
        text = message.content

        if context.context_type == TutorContextType.SCENARIO_BEFORE_DECISION and _matches_any(
            text, _ALL_SCENARIO_FUTURE_QUESTION_PHRASES
        ):
            return TutorGuardrailDecision(
                conversation_id=conversation_id,
                message_id=message.message_id,
                request_category=TutorRequestCategory.UNSUPPORTED_TOPIC,
                action=TutorGuardrailAction.REFUSE,
                matched_rule_codes=["SCENARIO_FUTURE_INFORMATION_REQUEST"],
                safe_response_override=localize(
                    LocalizedMessageKey.SCENARIO_FUTURE_INFORMATION_REFUSAL, language=language
                ),
                policy_version=self.policy_version,
            )

        if _claims_guaranteed_return(text):
            return TutorGuardrailDecision(
                conversation_id=conversation_id,
                message_id=message.message_id,
                request_category=TutorRequestCategory.GUARANTEED_RETURN_REQUEST,
                action=TutorGuardrailAction.REFUSE,
                matched_rule_codes=["GUARANTEED_RETURN"],
                safe_response_override=localize(LocalizedMessageKey.ADVICE_REFUSAL, language=language),
                policy_version=self.policy_version,
            )

        if _matches_any(text, _ALL_BUY_SELL_PHRASES):
            return TutorGuardrailDecision(
                conversation_id=conversation_id,
                message_id=message.message_id,
                request_category=TutorRequestCategory.BUY_SELL_REQUEST,
                action=TutorGuardrailAction.REFUSE,
                matched_rule_codes=["BUY_SELL_INSTRUCTION"],
                safe_response_override=localize(LocalizedMessageKey.ADVICE_REFUSAL, language=language),
                policy_version=self.policy_version,
            )

        if _matches_any(text, _ALL_PERSONALIZED_ALLOCATION_PHRASES):
            return TutorGuardrailDecision(
                conversation_id=conversation_id,
                message_id=message.message_id,
                request_category=TutorRequestCategory.PERSONALIZED_INVESTMENT_ADVICE,
                action=TutorGuardrailAction.ALLOW_WITH_BOUNDARY,
                matched_rule_codes=["PERSONALIZED_ALLOCATION"],
                safe_response_override=(
                    localize(LocalizedMessageKey.ADVICE_REFUSAL, language=language) + _boundary_suffix(language)
                ),
                policy_version=self.policy_version,
            )

        if apply_topic_vocabulary_check and _is_off_topic(text):
            return TutorGuardrailDecision(
                conversation_id=conversation_id,
                message_id=message.message_id,
                request_category=TutorRequestCategory.UNSUPPORTED_TOPIC,
                action=TutorGuardrailAction.FALLBACK,
                matched_rule_codes=["OFF_TOPIC"],
                safe_response_override=localize(LocalizedMessageKey.INSUFFICIENT_EVIDENCE, language=language),
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

        if _claims_guaranteed_return(answer_text):
            issues.append("GUARANTEED_RETURN_CLAIM")

        if _matches_any(answer_text, _ALL_BUY_SELL_PHRASES) or re.search(
            r"\b(buy|sell) (it|this|that|now|\d)", answer_text, re.IGNORECASE
        ):
            issues.append("DIRECT_BUY_SELL_INSTRUCTION")

        if context.context_type == TutorContextType.SCENARIO_BEFORE_DECISION and (
            re.search(
                r"\b(the (stock|price|market) (rose|fell|rallied|crashed|dropped)|the (correct|right) option "
                r"(is|was)|the outcome (is|was)|afterward|in hindsight|it turned out)\b",
                answer_text,
                re.IGNORECASE,
            )
            or _matches_any(answer_text, _HEBREW_SCENARIO_OUTCOME_LEAK_PHRASES)
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
        elif not cited_chunk_ids and answer_text not in _APPROVED_NON_CITED_TEXTS:
            status = GroundingStatus.INSUFFICIENT_EVIDENCE
        elif issues:
            status = GroundingStatus.PARTIALLY_GROUNDED
        else:
            status = GroundingStatus.GROUNDED

        return status, issues
