"""`ModelTranslationAdapter`: implements `TranslationPort` by reusing an
already-configured `TutorModelPort` (spec G2D2 section 6) - translation
is a small, bounded instruction-following task, not a reason to add a
second model-provider integration. Works with whichever adapter the
caller composes in (Ollama, the OpenAI-compatible adapter, or the future
OpenAI reasoning adapter).
"""

from __future__ import annotations

from stock_research_core.application.ai_tutor.models import TutorModelRequest
from stock_research_core.application.ai_tutor.ports import TutorModelPort
from stock_research_core.application.language.service import LanguageBridgeService

TRANSLATION_PROMPT_VERSION = "language-bridge-translation-v1"

_MAX_INPUT_CHARACTERS = 2000
_MAX_OUTPUT_TOKENS = 400

_SYSTEM_INSTRUCTIONS = (
    "You translate a learner's financial-education question from Hebrew to English for internal "
    "search purposes only. Translate the text below as literally and completely as possible. "
    "Preserve tickers, company names, and numbers unchanged. Do not answer the question, add "
    "commentary, or cite anything - respond with only the translated English text as answer_markdown, "
    "and always return an empty cited_chunk_ids list."
)


class ModelTranslationAdapter:
    """Never treats the translated text as evidence or a citation
    source: the underlying `TutorModelPort.generate()` call always
    receives an empty `retrieved_candidates` list, so its
    `cited_chunk_ids` result is always empty too - only `answer_markdown`
    (the translated text) is read."""

    def __init__(self, *, tutor_model: TutorModelPort, prompt_version: str = TRANSLATION_PROMPT_VERSION) -> None:
        self._tutor_model = tutor_model
        self._prompt_version = prompt_version

    async def translate_to_english(self, *, text: str) -> str:
        request = TutorModelRequest(
            system_instructions=_SYSTEM_INSTRUCTIONS,
            user_question=text[:_MAX_INPUT_CHARACTERS],
            conversation_messages=[],
            retrieved_candidates=[],
            structured_context={},
            prompt_version=self._prompt_version,
            maximum_output_tokens=_MAX_OUTPUT_TOKENS,
        )
        result = await self._tutor_model.generate(request)
        return result.answer_markdown.strip()


def build_language_bridge(*, enabled: bool, tutor_model: TutorModelPort) -> LanguageBridgeService:
    """Build the original G2D2 bridge for callers of that explicit API.

    Current tutor and worker composition roots use the provider-neutral
    `LanguageServicePort` through `build_language_service`. This helper is
    retained for direct bridge consumers and compatibility tests; it is not a
    `GroundedAITutorService` constructor dependency."""
    translator = ModelTranslationAdapter(tutor_model=tutor_model) if enabled else None
    return LanguageBridgeService(translator=translator, enabled=enabled)
