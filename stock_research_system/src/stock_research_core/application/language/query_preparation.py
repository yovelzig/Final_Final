"""The ONE bounded language-query preparation step (Phase G2E2A
correction pass, req. 3/5/6).

Every consumer of the Hebrew bridge - `GroundedAITutorService`, the
LangGraph learning coach's `GraphNodes`, and (per Phase G2D2) the Coach
research-resume path - calls `prepare_language_query()` exactly once per
request and then reuses the single `LanguageQueryPreparation` it returns
for *all* downstream English-only machinery: translated guardrail
defense-in-depth, intent classification, embedding/lexical retrieval, and
the Knowledge Sufficiency Gate. There is deliberately no second detector,
no second translator call per request, and no per-consumer copy of the
enabled/disabled decision.

Three hard rules this module exists to make structural:

1. **Detection reads the request text and nothing else.** No learner
   profile, account identifier, security/ticker, or client-supplied
   "language" claim is a parameter here, so none can influence it.
2. **The learner's original text is never replaced.** `original_text` is
   returned unchanged; `search_query` is a *separate* bounded English
   query used only to drive retrieval/classification. It is never
   persisted as the learner's own message, never treated as evidence, and
   never surfaced in a citation.
3. **Translation failure fails closed.** When a Hebrew request was
   detected and translation was attempted but failed,
   `translation_failed` is `True` and `search_query` is *not* usable -
   callers must return their exact localized bounded fallback rather than
   continuing into retrieval, intent classification, or model
   generation with untranslated Hebrew (see
   `LanguageQueryPreparation.translation_failed`).

Nothing here touches a database: `prepare_language_query()` performs the
one external translation call, so callers can (and must, per req. 5)
invoke it strictly outside any open Unit of Work / DB transaction.
"""

from __future__ import annotations

from dataclasses import dataclass

from stock_research_core.application.exceptions import LanguageServiceError
from stock_research_core.application.language.enums import DetectedLanguage
from stock_research_core.application.language.models import MAX_TRANSLATED_QUERY_LENGTH
from stock_research_core.application.language.ports import LanguageServicePort


@dataclass(frozen=True)
class LanguageQueryPreparation:
    """The result of one bounded language-query preparation.

    `search_query` is only meaningful when `translation_failed` is
    `False`. For an English request (or a disabled feature flag) it is
    the original text verbatim, so every existing English code path is
    byte-identical to before this phase.
    """

    original_text: str
    detected_language: DetectedLanguage
    search_query: str
    translation_attempted: bool
    translation_failed: bool

    @property
    def is_hebrew(self) -> bool:
        return self.detected_language == DetectedLanguage.HE

    @property
    def translation_succeeded(self) -> bool:
        return self.translation_attempted and not self.translation_failed


def detect_request_language(
    language_service: LanguageServicePort, *, enabled: bool, text: str
) -> DetectedLanguage:
    """This request's language, from its text alone.

    Pure and free (a Unicode-range scan - no model call, no network), so
    callers can run it *before* the deterministic guardrail and skip
    translating a request the guardrail already refuses. `enabled=False`
    (the production default, `HEBREW_QUERY_BRIDGE_ENABLED=false`)
    short-circuits before `detect_language()` is called at all - a
    disabled deployment runs zero new code for any request.
    """
    if not enabled:
        return DetectedLanguage.EN
    return language_service.detect_language(text)


def untranslated_preparation(text: str, detected_language: DetectedLanguage) -> LanguageQueryPreparation:
    """The preparation for a request that must NOT be translated at all -
    today, one the guardrail already refused on the learner's own words.

    `translation_attempted=False` and `translation_failed=False`: nothing
    was tried and nothing failed, so a caller can still distinguish this
    from the fail-closed case. `search_query` is the original text and is
    never used - a refused request reaches no retriever and no model.
    """
    return LanguageQueryPreparation(
        original_text=text, detected_language=detected_language, search_query=text,
        translation_attempted=False, translation_failed=False,
    )


async def prepare_language_query(
    language_service: LanguageServicePort,
    *,
    enabled: bool,
    text: str,
    detected_language: DetectedLanguage | None = None,
) -> LanguageQueryPreparation:
    """Detect once, translate at most once, and return the single bounded
    English query every downstream English-only component must reuse.

    `detected_language` lets a caller that already ran
    `detect_request_language()` (to decide whether translating is even
    appropriate) pass the result in rather than re-deriving it - detection
    is pure, so this is about keeping one answer per request, not about
    cost.
    """
    if not enabled:
        return LanguageQueryPreparation(
            original_text=text, detected_language=DetectedLanguage.EN, search_query=text,
            translation_attempted=False, translation_failed=False,
        )

    if detected_language is None:
        detected_language = language_service.detect_language(text)
    if detected_language != DetectedLanguage.HE:
        return LanguageQueryPreparation(
            original_text=text, detected_language=detected_language, search_query=text,
            translation_attempted=False, translation_failed=False,
        )

    try:
        translation = await language_service.translate_to_english_query(text, source_language=detected_language)
    except LanguageServiceError:
        # Fail closed (req. 6): `search_query` is deliberately left as the
        # original text so nothing can accidentally read a fabricated
        # query, but `translation_failed=True` is what callers branch on -
        # they must return their exact localized bounded fallback instead
        # of searching an English-only corpus with Hebrew text and hoping
        # it returns zero candidates.
        return LanguageQueryPreparation(
            original_text=text, detected_language=detected_language, search_query=text,
            translation_attempted=True, translation_failed=True,
        )

    return LanguageQueryPreparation(
        original_text=text, detected_language=detected_language,
        search_query=translation.translated_query[:MAX_TRANSLATED_QUERY_LENGTH],
        translation_attempted=True, translation_failed=False,
    )
