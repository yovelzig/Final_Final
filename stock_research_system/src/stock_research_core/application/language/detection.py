"""Deterministic, bounded Unicode-based language detection (Phase G2E2A).

Pure function only - no ML classifier, no external call, no randomness,
matching the same determinism bar already documented for
`application.ai_tutor.guardrails` and `application.ai_tutor.sufficiency`.

`detect_language()` takes only the raw question text. It is never given a
learner profile, account identifier, or security/ticker field to
consult - there is no parameter through which one could be passed, so a
client-supplied "language" claim (which does not exist anywhere in this
codebase's tutor API) could never influence it even if one were added
elsewhere by mistake.
"""

from __future__ import annotations

from stock_research_core.application.language.enums import DetectedLanguage

#: Hebrew block + Hebrew presentation forms. Deliberately does not
#: include Arabic, Syriac, or other RTL scripts - Phase G2E2A's scope is
#: English/Hebrew only.
_HEBREW_UNICODE_RANGES: tuple[tuple[int, int], ...] = (
    (0x0590, 0x05FF),
    (0xFB1D, 0xFB4F),
)

#: A Hebrew-letter share of all alphabetic characters at or above this
#: ratio classifies the text as Hebrew - chosen so a mostly-Hebrew
#: question that also contains English financial terminology or tickers
#: (spec requirement: mixed-language support) still classifies as
#: Hebrew, while a mostly-English question with an occasional Hebrew
#: word still classifies as English.
_MINIMUM_HEBREW_RATIO = 0.3

#: Bounded scan: detection never needs to look past the first few
#: hundred characters to classify a script reliably, and this keeps the
#: function's cost independent of the caller's own length limits
#: (`AskQuestionRequest.question` is already capped at 10,000 characters
#: upstream; this is a second, independent bound).
_MAX_SCAN_CHARACTERS = 2000


def _is_hebrew_letter(character: str) -> bool:
    codepoint = ord(character)
    return any(low <= codepoint <= high for low, high in _HEBREW_UNICODE_RANGES)


def detect_language(text: str) -> DetectedLanguage:
    """Classify `text` as `DetectedLanguage.HE` or `DetectedLanguage.EN`.

    Counts Hebrew-block letters against all alphabetic characters
    (Hebrew or otherwise) in the first `_MAX_SCAN_CHARACTERS` characters
    of `text`. Empty, whitespace-only, or purely non-alphabetic input
    (digits/punctuation/tickers only) defaults to `EN` - the safe
    default matching this system's existing English-only behavior.
    """
    hebrew_count = 0
    alphabetic_count = 0
    for character in text[:_MAX_SCAN_CHARACTERS]:
        if _is_hebrew_letter(character):
            hebrew_count += 1
            alphabetic_count += 1
        elif character.isalpha():
            alphabetic_count += 1

    if alphabetic_count == 0:
        return DetectedLanguage.EN
    return DetectedLanguage.HE if (hebrew_count / alphabetic_count) >= _MINIMUM_HEBREW_RATIO else DetectedLanguage.EN


# Compatibility name bound to the canonical enum class; not a second enum.
Language = DetectedLanguage
