"""Deterministic current-information decision policy (spec G2D2 section
10) - a pure function, no I/O, no LLM. Decides whether a learner
question can stay in the static, approved Tutor RAG corpus or must be
routed to Live Research, and if so which `ResearchScope`.

Bounded EN+HE keyword table only - the same auditability tradeoff
already documented for `ai_tutor.sufficiency.is_current_information_request`
(which this module deliberately does not replace: that gate decides
whether *retrieved Tutor evidence* is strong enough, independent of
subject; this policy decides whether the question is asking about
*current/live information at all*, independent of retrieval).
`MARKET_DATA_SNAPSHOT` is never a possible output - spec section 10
explicitly excludes it, since no Live Research provider port exists for
it (see `application.operations.models.LiveResearchRunExecutionParameters
._reject_market_data_snapshot`).

Whether the subject is *ambiguous* (and therefore needs a clarification
response instead of a research job) is not decided here - that requires
actually attempting subject resolution (a later phase's concern, at the
point a `ResearchRequest` would be built), so this module only ever
returns `STATIC` or `CURRENT_INFORMATION` (with a scope).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from stock_research_core.application.language.detection import Language
from stock_research_core.domain.live_research.enums import ResearchScope


class InformationNeed(StrEnum):
    #: Stays in the static, approved Tutor RAG corpus.
    STATIC = "STATIC"
    #: Needs Live Research - see `CurrentInformationDecision.scope`.
    CURRENT_INFORMATION = "CURRENT_INFORMATION"


@dataclass(frozen=True)
class CurrentInformationDecision:
    need: InformationNeed
    scope: ResearchScope | None = None
    matched_keyword: str | None = None


def _patterns(*phrases: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(r"\b" + phrase + r"\b", re.IGNORECASE) for phrase in phrases)


# -- most specific first: a filing-review match must never be
# -- shadowed by a more generic "recent"/"latest" news match -----------------------------------------------

_FINANCIAL_FILING_PATTERNS = _patterns(
    r"latest filing", r"new filing", r"recent filing", r"latest 10-k", r"latest 10-q", r"quarterly report",
    r"annual report",
) + (
    re.compile(r"דוח אחרון", re.IGNORECASE),  # "דוח אחרון" - latest report/filing
    re.compile(r"דיווח אחרון", re.IGNORECASE),  # "דיווח אחרון" - latest filing
)

_ANALYST_SENTIMENT_PATTERNS = _patterns(
    r"analyst sentiment", r"current analyst", r"latest analyst", r"analyst rating", r"price target",
) + (
    re.compile(r"סנטימנט אנליסט", re.IGNORECASE),  # "סנטימנט אנליסט"
    re.compile(r"דירוג אנליסט", re.IGNORECASE),  # "דירוג אנליסט" - analyst rating
)

_COMPANY_OVERVIEW_PATTERNS = _patterns(
    r"current ceo", r"new ceo", r"current management", r"executive situation", r"leadership change",
) + (
    re.compile(r"מנכ\"ל נוכחי", re.IGNORECASE),  # 'מנכ"ל נוכחי' - current CEO
    re.compile(r"הנהלה נוכחית", re.IGNORECASE),  # "הנהלה נוכחית" - current management
)

_NEWS_SCAN_PATTERNS = _patterns(
    r"latest", r"current", r"today", r"yesterday", r"recently", r"this week", r"this month", r"recent news",
    r"what happened", r"what'?s happening",
) + (
    re.compile(r"היום", re.IGNORECASE),  # "היום" - today
    re.compile(r"אתמול", re.IGNORECASE),  # "אתמול" - yesterday
    re.compile(r"השבוע", re.IGNORECASE),  # "השבוע" - this week
    re.compile(r"לאחרונה", re.IGNORECASE),  # "לאחרונה" - recently
    re.compile(r"עדכני", re.IGNORECASE),  # "עדכני" - current/up-to-date
    re.compile(r"נוכחי", re.IGNORECASE),  # "נוכחי" - current
    re.compile(r"מה קרה", re.IGNORECASE),  # "מה קרה" - what happened
)


#: Stable finance terminology that merely contains "current" as a
#: modifier (current ratio, current yield, current assets/liabilities) -
#: excluded first, mirroring `ai_tutor.sufficiency`'s own
#: `_STABLE_FINANCE_TERMS`, so these are never misclassified as a
#: live-information request.
_STABLE_FINANCE_TERMS = re.compile(r"\bcurrent (ratio|yield|assets|liabilities)\b", re.IGNORECASE)


def _first_match(patterns: tuple[re.Pattern[str], ...], text: str) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def classify_information_need(question: str, *, language: Language | None = None) -> CurrentInformationDecision:
    """`language` is accepted but not required - every pattern table
    already carries both English and Hebrew entries, so detection is
    unnecessary for correctness; the parameter exists only so a caller
    that already ran `detect_language` doesn't need to re-derive it."""
    del language  # bounded pattern tables already cover both languages

    if _STABLE_FINANCE_TERMS.search(question):
        return CurrentInformationDecision(need=InformationNeed.STATIC)

    for scope, patterns in (
        (ResearchScope.FINANCIAL_FILING_REVIEW, _FINANCIAL_FILING_PATTERNS),
        (ResearchScope.ANALYST_SENTIMENT, _ANALYST_SENTIMENT_PATTERNS),
        (ResearchScope.COMPANY_OVERVIEW, _COMPANY_OVERVIEW_PATTERNS),
        (ResearchScope.NEWS_SCAN, _NEWS_SCAN_PATTERNS),
    ):
        matched = _first_match(patterns, question)
        if matched:
            return CurrentInformationDecision(need=InformationNeed.CURRENT_INFORMATION, scope=scope, matched_keyword=matched)

    return CurrentInformationDecision(need=InformationNeed.STATIC)
