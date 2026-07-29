"""`LanguageBridgeService`: the single application-layer entry point for
the shared EN/HE bridge (spec G2D2 section 6).

Consumed by `GroundedAITutorService` today; Live Research request
construction (a later phase) reuses the same service so retrieval-query
and research-query translation never drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stock_research_core.application.language.detection import Language, detect_language


@dataclass(frozen=True)
class RetrievalQueryPreparation:
    #: The text to actually search with - the original question unless
    #: translation was enabled, needed (Hebrew), and succeeded.
    retrieval_query: str
    detected_language: Language
    translated: bool


class LanguageBridgeService:
    """Preserves the original learner question exactly (this service
    never mutates or returns it) and produces a bounded, English
    *retrieval* query when the bridge is enabled and the question is
    Hebrew. Translation is never evidence and never a citation - it only
    ever feeds a retrieval/research query. A translation failure is
    always absorbed here: it never crashes, never calls a model with
    unrelated material (only ever the original question, unchanged),
    and always falls back to searching with the original text."""

    def __init__(self, *, translator: Any | None, enabled: bool) -> None:
        self._translator = translator
        self._enabled = enabled

    async def prepare_retrieval_query(self, original_question: str) -> RetrievalQueryPreparation:
        detected_language = detect_language(original_question)
        if not self._enabled or detected_language != Language.HEBREW or self._translator is None:
            return RetrievalQueryPreparation(
                retrieval_query=original_question, detected_language=detected_language, translated=False
            )

        try:
            translated_query = await self._translator.translate_to_english(text=original_question)
        except Exception:  # noqa: BLE001 - a translation-provider failure must never crash `ask()`
            return RetrievalQueryPreparation(
                retrieval_query=original_question, detected_language=detected_language, translated=False
            )

        translated_query = translated_query.strip()
        if not translated_query:
            return RetrievalQueryPreparation(
                retrieval_query=original_question, detected_language=detected_language, translated=False
            )
        return RetrievalQueryPreparation(
            retrieval_query=translated_query, detected_language=detected_language, translated=True
        )
