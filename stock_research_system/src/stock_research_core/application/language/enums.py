"""Enumerations for the shared, cross-cutting language service (Phase G2E2A).

No infrastructure import here - the same "pure" rule every other
`domain`/`application` enum module in this codebase follows.
"""

from __future__ import annotations

from enum import StrEnum


class DetectedLanguage(StrEnum):
    """The deterministic output of `detection.detect_language()`.

    Only two values today (English and Hebrew) - matching the Phase
    G2E2A scope. Every consumer that receives a `DetectedLanguage` must
    treat unrecognized/future values the same way it treats `EN` (the
    safe, English-only default), never raise.
    """

    EN = "EN"
    ENGLISH = "EN"
    HE = "HE"
    HEBREW = "HE"


class LocalizedMessageKey(StrEnum):
    """Which exact, approved safety string a `LanguageServicePort.localize()`
    call is asking for - never a free-form message key, so every caller
    (the tutor guardrail, `GroundedAITutorService`, the LangGraph coach)
    selects from the same fixed, auditable set."""

    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    ADVICE_REFUSAL = "ADVICE_REFUSAL"
    SCENARIO_FUTURE_INFORMATION_REFUSAL = "SCENARIO_FUTURE_INFORMATION_REFUSAL"
    RESEARCH_UNAVAILABLE = "RESEARCH_UNAVAILABLE"
    RESEARCH_WAITING = "RESEARCH_WAITING"
    RESEARCH_NO_EVIDENCE = "RESEARCH_NO_EVIDENCE"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    CLARIFICATION_NEEDED_COMPANY = "CLARIFICATION_NEEDED_COMPANY"
