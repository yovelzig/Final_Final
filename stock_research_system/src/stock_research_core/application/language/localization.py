"""Static, exact-approved localized strings for the shared language
service (Phase G2E2A).

Every value here IS one of the exact, validator-approved `EXACT_*`
constants already defined in `domain.ai_tutor.models` - `localize()`
never generates, paraphrases, or otherwise freshly produces a string. A
single shared table and lookup function so every consumer (the tutor
guardrail, `GroundedAITutorService`'s own fallback text, the
`UnavailableLanguageService`/`LlmBackedLanguageService` port
implementations, and the LangGraph learning coach) resolves the same
string for the same `(key, language)` pair - never a second, drifting
copy.
"""

from __future__ import annotations

from stock_research_core.application.language.enums import DetectedLanguage, LocalizedMessageKey
from stock_research_core.domain.ai_tutor.models import (
    EXACT_ADVICE_REFUSAL,
    EXACT_ADVICE_REFUSAL_HE,
    EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
    EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE,
    EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL,
    EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL_HE,
)

LOCALIZED_STRINGS: dict[LocalizedMessageKey, dict[DetectedLanguage, str]] = {
    LocalizedMessageKey.INSUFFICIENT_EVIDENCE: {
        DetectedLanguage.EN: EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
        DetectedLanguage.HE: EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE,
    },
    LocalizedMessageKey.ADVICE_REFUSAL: {
        DetectedLanguage.EN: EXACT_ADVICE_REFUSAL,
        DetectedLanguage.HE: EXACT_ADVICE_REFUSAL_HE,
    },
    LocalizedMessageKey.SCENARIO_FUTURE_INFORMATION_REFUSAL: {
        DetectedLanguage.EN: EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL,
        DetectedLanguage.HE: EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL_HE,
    },
}


def localize(key: LocalizedMessageKey, *, language: DetectedLanguage) -> str:
    """The exact, approved string for `key` in `language`. Falls back to
    the English string for any language not present for `key` (there is
    none today - every key has both `EN` and `HE` - but this keeps the
    lookup total rather than raising `KeyError` if a future language is
    added to `DetectedLanguage` before this table is updated for it)."""
    strings_by_language = LOCALIZED_STRINGS[key]
    return strings_by_language.get(language, strings_by_language[DetectedLanguage.EN])
