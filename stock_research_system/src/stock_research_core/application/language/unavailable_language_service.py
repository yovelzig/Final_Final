"""Safe default `LanguageServicePort` adapter (Phase G2E2A).

Pure Python only - no SQLAlchemy, httpx, or LLM-SDK dependency, exactly
like `application.ai_tutor.sufficiency.DisabledKnowledgeSufficiencyGate`
(the same "pure default lives beside the Protocol, not under
`infrastructure`" convention this codebase already follows). Composed
whenever Hebrew translation is disabled, or no translation-capable
provider is configured - detection and localization are always free and
available; only translation is refused.
"""

from __future__ import annotations

from stock_research_core.application.exceptions import LanguageServiceError
from stock_research_core.application.language.detection import detect_language
from stock_research_core.application.language.enums import DetectedLanguage, LocalizedMessageKey
from stock_research_core.application.language.localization import localize
from stock_research_core.application.language.models import TranslationResult


class UnavailableLanguageService:
    """`detect_language`/`localize` work normally and never fail;
    `translate_to_english_query` always raises `LanguageServiceError`.
    Satisfies `LanguageServicePort`.

    Composing this (instead of a translation-capable adapter) is what
    makes Hebrew translation itself opt-in and rollback-safe: every
    caller's existing translation-failure degrade path (fall back to the
    original-language text as the retrieval/search query, which then
    naturally yields an insufficient-evidence fallback) is the *only*
    thing that can happen for a non-English question composed with this
    adapter - never a fabricated or silently English-only answer.
    """

    def detect_language(self, text: str) -> DetectedLanguage:
        return detect_language(text)

    def localize(self, key: LocalizedMessageKey, *, language: DetectedLanguage) -> str:
        return localize(key, language=language)

    async def translate_to_english_query(
        self, text: str, *, source_language: DetectedLanguage
    ) -> TranslationResult:
        del text, source_language
        raise LanguageServiceError("No translation-capable language-service provider is configured.")
