"""Application-level result model for the shared language service (Phase G2E2A).

Plain Pydantic model; no SQLAlchemy, httpx, or LLM-SDK dependency here.
"""

from __future__ import annotations

from pydantic import ConfigDict, Field

from stock_research_core.application.language.enums import DetectedLanguage
from stock_research_core.domain.models import DomainModel

#: A bounded English retrieval/search query, never a full translated
#: answer or document - short enough that it can never plausibly carry a
#: fabricated "fact" a downstream consumer could mistake for evidence.
MAX_TRANSLATED_QUERY_LENGTH = 500

#: Bounds how much of a learner's original text is ever sent to a
#: translation provider, independent of any upstream caller's own limit
#: (`TutorMessage.content` is already capped at 10,000 characters) - a
#: second, provider-adapter-local bound, matching
#: `application.language.detection`'s own `_MAX_SCAN_CHARACTERS`.
MAX_TRANSLATION_INPUT_LENGTH = 2000


class TranslationQueryPayload(DomainModel):
    """The **only** shape a translation provider's structured JSON output
    may take: exactly `{"query": "..."}`, nothing more.

    Used to strictly validate a provider's raw response before it is
    ever wrapped into a `TranslationResult` - `extra="forbid"` rejects
    any additional key (e.g. a model that ignores instructions and also
    returns `answer_markdown`/`cited_chunk_ids`, the *Tutor's own*
    response shape), and the length bound rejects an oversized query
    outright rather than silently truncating it. Any
    `pydantic.ValidationError` raised while constructing this model must
    be caught by the caller and re-raised as `LanguageServiceError` -
    never allowed to propagate as a raw Pydantic error.
    """

    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, validate_assignment=True, protected_namespaces=(),
    )

    query: str = Field(min_length=1, max_length=MAX_TRANSLATED_QUERY_LENGTH)


class TranslationResult(DomainModel):
    """The result of one `LanguageServicePort.translate_to_english_query()`
    call.

    `translated_query` is explicitly a *query*, not an answer - callers
    must only ever use it to drive retrieval/search, never treat it as a
    factual claim, never persist it as the learner's own message, and
    never surface it as (or fold it into) a citation.
    """

    translated_query: str = Field(min_length=1, max_length=MAX_TRANSLATED_QUERY_LENGTH)
    source_language: DetectedLanguage
    translation_policy_version: str = Field(min_length=1, max_length=50)
