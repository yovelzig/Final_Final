"""Bounded, literal English/Hebrew learner-safe message pairs (spec
G2D2 section 6). Every value here is a fixed, reviewed string - never
model-generated - exactly the same guarantee `domain.ai_tutor.models.
EXACT_INSUFFICIENT_EVIDENCE_FALLBACK`/`EXACT_ADVICE_REFUSAL` already give
the English-only paths. The English entries below reuse those exact
constants verbatim so the two never drift apart.
"""

from __future__ import annotations

from enum import StrEnum

from stock_research_core.application.language.detection import Language
from stock_research_core.domain.ai_tutor.models import (
    EXACT_ADVICE_REFUSAL,
    EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
    EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL,
)


class LocalizedMessageKey(StrEnum):
    INSUFFICIENT_MATERIAL = "INSUFFICIENT_MATERIAL"
    UNSAFE_INVESTMENT_ADVICE = "UNSAFE_INVESTMENT_ADVICE"
    SCENARIO_FUTURE_INFORMATION_REFUSAL = "SCENARIO_FUTURE_INFORMATION_REFUSAL"
    RESEARCH_UNAVAILABLE = "RESEARCH_UNAVAILABLE"
    RESEARCH_PENDING = "RESEARCH_PENDING"
    RESEARCH_NO_EVIDENCE = "RESEARCH_NO_EVIDENCE"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    #: A FINANCIAL_FILING_REVIEW/COMPANY_OVERVIEW request whose company
    #: could not be resolved to exactly one authoritative SEC CIK -
    #: missing or ambiguous (spec G2D2/H1 correction pass, section 5).
    #: Never a silent NEWS_SCAN downgrade.
    CLARIFICATION_NEEDED_COMPANY = "CLARIFICATION_NEEDED_COMPANY"


_MESSAGES: dict[LocalizedMessageKey, dict[Language, str]] = {
    LocalizedMessageKey.INSUFFICIENT_MATERIAL: {
        Language.ENGLISH: EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
        Language.HEBREW: "אין לי מספיק חומר מאושר של FinQuest כדי לענות על כך בביטחון.",
    },
    LocalizedMessageKey.UNSAFE_INVESTMENT_ADVICE: {
        Language.ENGLISH: EXACT_ADVICE_REFUSAL,
        Language.HEBREW: (
            "אני יכול להסביר את המושגים, הסיכונים והדוגמאות החינוכיות, "
            "אך אינני יכול לומר לך מה לקנות, למכור או להשקיע באופן אישי."
        ),
    },
    LocalizedMessageKey.SCENARIO_FUTURE_INFORMATION_REFUSAL: {
        Language.ENGLISH: EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL,
        Language.HEBREW: "אינני יכול לחשוף מידע על תוצאה עתידית של תרחיש לפני קבלת ההחלטה שלך.",
    },
    LocalizedMessageKey.RESEARCH_UNAVAILABLE: {
        Language.ENGLISH: "Current research is temporarily unavailable. Please try again shortly.",
        Language.HEBREW: "מחקר עדכני אינו זמין כרגע. נסה שוב בעוד זמן קצר.",
    },
    LocalizedMessageKey.RESEARCH_PENDING: {
        Language.ENGLISH: "I'm gathering current information to answer that - this may take a moment.",
        Language.HEBREW: "אני אוסף מידע עדכני כדי לענות על כך - זה עשוי לקחת רגע.",
    },
    LocalizedMessageKey.RESEARCH_NO_EVIDENCE: {
        Language.ENGLISH: "I looked for current, approved information on that but couldn't find enough to answer reliably.",
        Language.HEBREW: "חיפשתי מידע עדכני ומאושר בנושא זה אך לא מצאתי מספיק כדי לענות בביטחון.",
    },
    LocalizedMessageKey.PROVIDER_FAILURE: {
        Language.ENGLISH: "I couldn't complete that research request right now. Please try again shortly.",
        Language.HEBREW: "לא הצלחתי להשלים את בקשת המחקר כעת. נסה שוב בעוד זמן קצר.",
    },
    LocalizedMessageKey.CLARIFICATION_NEEDED_COMPANY: {
        Language.ENGLISH: (
            "Could you tell me the exact company name or ticker symbol you mean? "
            "I want to make sure I look up the right company's filing."
        ),
        Language.HEBREW: (
            "תוכל לציין את שם החברה המדויק או סמל המסחר שלה? "
            "אני רוצה לוודא שאני בודק את הדיווח של החברה הנכונה."
        ),
    },
}


def localized_message(key: LocalizedMessageKey, *, language: Language) -> str:
    return _MESSAGES[key][language]
