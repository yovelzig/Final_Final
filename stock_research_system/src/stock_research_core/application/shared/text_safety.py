"""`SharedTextSafetyValidator` (spec G2D2 section 17): a bounded-length,
markup-stripping safety pass for learner-facing generated text - shared
by the Tutor path and Live Research synthesis so the two never diverge
on what "safe to show a learner" means. Never a content-moderation
classifier; purely deterministic bounding: caps length and strips raw
HTML/script-shaped markup, exactly the same auditability tradeoff
already documented for `ai_tutor.guardrails.RuleBasedTutorGuardrail`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_MAX_CHARACTERS = 5_000

#: `<script>`/`<iframe>`/`javascript:`/inline event-handler-shaped
#: content - bounded, deterministic, not a full HTML sanitizer (no
#: markdown renders raw HTML in this codebase's learner-facing UI, so
#: this is defense in depth, not the only line of defense).
_UNSAFE_MARKUP_PATTERN = re.compile(
    r"<\s*script\b.*?>.*?<\s*/\s*script\s*>|<\s*iframe\b[^>]*>.*?<\s*/\s*iframe\s*>|javascript\s*:|on\w+\s*=\s*['\"]",
    re.IGNORECASE | re.DOTALL,
)
_ANY_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class TextSafetyDecision:
    bounded_text: str
    issue_codes: list[str]


class SharedTextSafetyValidator:
    def __init__(self, *, max_characters: int = DEFAULT_MAX_CHARACTERS) -> None:
        self._max_characters = max_characters

    def validate(self, text: str) -> TextSafetyDecision:
        issue_codes: list[str] = []
        bounded = text

        if _UNSAFE_MARKUP_PATTERN.search(bounded):
            issue_codes.append("UNSAFE_MARKUP_STRIPPED")
            bounded = _UNSAFE_MARKUP_PATTERN.sub("", bounded)
            bounded = _ANY_HTML_TAG_PATTERN.sub("", bounded)

        if len(bounded) > self._max_characters:
            issue_codes.append("TEXT_TRUNCATED")
            bounded = bounded[: self._max_characters]

        return TextSafetyDecision(bounded_text=bounded, issue_codes=issue_codes)
