"""Application-level Protocol for the shared, cross-cutting language service
(Phase G2E2A).

Pure `Protocol` definition - no SQLAlchemy, httpx, or LLM-SDK import here.
Exactly one concrete implementation is built per process (composed once
in `api.app_factory` and shared, by construction, across
`GroundedAITutorService`, the LangGraph learning coach's `NodeDependencies`,
and `LiveResearchRunExecutionJobHandler`) - never a second or third
translator implementation.
"""

from __future__ import annotations

from typing import Protocol

from stock_research_core.application.language.enums import DetectedLanguage, LocalizedMessageKey
from stock_research_core.application.language.models import TranslationResult


class LanguageServicePort(Protocol):
    """Deterministic language detection/localization, plus a bounded,
    explicit translation call used only to build a retrieval/search
    query - never evidence, never the text shown to the learner as their
    own question."""

    def detect_language(self, text: str) -> DetectedLanguage:
        """A pure function of `text` alone. Never given a learner
        profile, account identifier, or security/ticker field - there is
        no parameter through which one could be passed."""
        ...

    async def translate_to_english_query(
        self, text: str, *, source_language: DetectedLanguage
    ) -> TranslationResult:
        """Raises `application.exceptions.LanguageServiceError` on any
        failure (missing/misconfigured provider, transient network
        failure after bounded retries, unusable response) - never
        returns a fabricated or empty query, and never raises anything
        else."""
        ...

    def localize(self, key: LocalizedMessageKey, *, language: DetectedLanguage) -> str:
        """Returns one of the fixed, exact, approved safety strings for
        `key`/`language` - never a freshly generated or paraphrased
        message."""
        ...
