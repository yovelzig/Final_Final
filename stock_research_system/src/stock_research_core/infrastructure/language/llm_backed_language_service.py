"""LLM-backed `LanguageServicePort` adapter (Phase G2E2A).

Talks to a configured chat endpoint using a short, distinct "translate,
do not answer" prompt - never the tutor's own `system_instructions`, and
never the tutor model itself mid-answer. Supports two wire shapes so it
can reuse whichever server-side Tutor model provider is already
configured (see `infrastructure.language.composition.build_language_service`)
rather than requiring a second, separately-configured translation
provider:

- `wire_shape="openai_compatible"` (default): `POST {base_url}/chat/completions`,
  mirroring `infrastructure.ai_tutor.openai_compatible_tutor.OpenAICompatibleTutorAdapter`.
- `wire_shape="ollama_cloud"`: `POST {base_url}/chat` (native, non-OpenAI-compatible
  shape), mirroring `infrastructure.ai_tutor.ollama_cloud_tutor.OllamaCloudTutorAdapter`.

Both shapes share one bounded-retry loop and one strict response
validator (`application.language.models.TranslationQueryPayload`) - this
is deliberately still a single provider-adapter class/port
implementation (never a second `LanguageServicePort` class per wire
shape), matching the "reuse, don't duplicate" rule the rest of
`application.language`/`infrastructure.language` follows.

`detect_language`/`localize` are pure and never make a network call;
only `translate_to_english_query` does.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pydantic

from stock_research_core.application.exceptions import LanguageServiceError
from stock_research_core.application.language.detection import detect_language
from stock_research_core.application.language.enums import DetectedLanguage, LocalizedMessageKey
from stock_research_core.application.language.localization import localize
from stock_research_core.application.language.models import (
    MAX_TRANSLATION_INPUT_LENGTH,
    TranslationQueryPayload,
    TranslationResult,
)

TRANSLATION_POLICY_VERSION = "language-service-llm-backed-v1"

_SUPPORTED_WIRE_SHAPES = frozenset({"openai_compatible", "ollama_cloud"})
_MAX_TRANSIENT_RETRIES = 2
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_MAX_TRANSLATION_OUTPUT_TOKENS = 120

_TRANSLATION_SYSTEM_PROMPT = (
    "You translate a financial-education learner's question into a short English search "
    "query suitable for retrieving relevant documents. Do not answer the question. Do not "
    "add facts, numbers, or information that is not already implied by the question. Do not "
    "use markdown or code fences. "
    'Respond with a single JSON object of exactly this shape, and nothing else: {"query": "string"}'
)


class LlmBackedLanguageService:
    """Calls a configured chat endpoint to translate a non-English
    question into a bounded, strictly-validated English retrieval
    query. Satisfies `LanguageServicePort`."""

    policy_version = TRANSLATION_POLICY_VERSION

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        wire_shape: str = "openai_compatible",
        timeout_seconds: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if wire_shape not in _SUPPORTED_WIRE_SHAPES:
            raise ValueError(f"Unsupported wire_shape {wire_shape!r}; must be one of {sorted(_SUPPORTED_WIRE_SHAPES)}")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_name = model_name
        self._wire_shape = wire_shape
        self._timeout_seconds = timeout_seconds
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def detect_language(self, text: str) -> DetectedLanguage:
        return detect_language(text)

    def localize(self, key: LocalizedMessageKey, *, language: DetectedLanguage) -> str:
        return localize(key, language=language)

    async def translate_to_english_query(
        self, text: str, *, source_language: DetectedLanguage
    ) -> TranslationResult:
        bounded_text = text[:MAX_TRANSLATION_INPUT_LENGTH]
        raw_response = await self._call_model(bounded_text)
        content = self._extract_content(raw_response)
        translated_query = self._validate_and_extract_query(content)
        return TranslationResult(
            translated_query=translated_query, source_language=source_language,
            translation_policy_version=self.policy_version,
        )

    # -- request -----------------------------------------------

    def _build_payload(self, text: str) -> dict:
        messages = [
            {"role": "system", "content": _TRANSLATION_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]
        if self._wire_shape == "ollama_cloud":
            return {
                "model": self._model_name, "messages": messages, "stream": False, "think": False,
                "options": {"temperature": 0, "num_predict": _MAX_TRANSLATION_OUTPUT_TOKENS},
            }
        return {
            "model": self._model_name, "messages": messages,
            "max_tokens": _MAX_TRANSLATION_OUTPUT_TOKENS, "temperature": 0,
        }

    def _endpoint(self) -> str:
        if self._wire_shape == "ollama_cloud":
            return f"{self._base_url}/chat"
        return f"{self._base_url}/chat/completions"

    async def _call_model(self, text: str) -> dict:
        payload = self._build_payload(text)
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        last_error: Exception | None = None
        for attempt in range(_MAX_TRANSIENT_RETRIES + 1):
            try:
                response = await self._client.post(self._endpoint(), json=payload, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt < _MAX_TRANSIENT_RETRIES:
                    await asyncio.sleep(0)
                    continue
                raise LanguageServiceError(
                    "The configured translation endpoint was unreachable after retrying."
                ) from exc

            if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_TRANSIENT_RETRIES:
                last_error = LanguageServiceError(
                    f"Transient HTTP {response.status_code} from translation endpoint"
                )
                await asyncio.sleep(0)
                continue

            if response.status_code >= 400:
                # Never expose the raw provider response body - only the status code.
                raise LanguageServiceError(
                    f"The configured translation endpoint returned HTTP {response.status_code}."
                )

            try:
                return response.json()
            except ValueError as exc:
                raise LanguageServiceError(
                    "The configured translation endpoint returned a non-JSON response."
                ) from exc

        raise LanguageServiceError(
            "The configured translation endpoint was unreachable after retrying."
        ) from last_error

    # -- response validation -----------------------------------------------

    def _extract_content(self, raw_response: dict) -> str | None:
        try:
            if self._wire_shape == "ollama_cloud":
                content = raw_response["message"]["content"]
            else:
                content = raw_response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None
        return content if isinstance(content, str) else None

    def _validate_and_extract_query(self, content: str | None) -> str:
        """Strict validation (spec ss7): the provider's response must be
        exactly `{"query": "..."}`, the query must not still be Hebrew
        (a "successful" translation that didn't actually translate is
        treated as a failure), and every rejection path raises only
        `LanguageServiceError` - never a raw parsing/Pydantic exception,
        and never the raw provider response content."""
        if content is None:
            raise LanguageServiceError("The configured translation endpoint returned no usable content.")
        # Reject markdown/code-fenced output outright rather than
        # attempting to strip and leniently parse it - an instruction-
        # following model never needs this, and a model that ignores the
        # "no markdown" instruction is not trustworthy enough to parse
        # around silently.
        if "```" in content:
            raise LanguageServiceError("The configured translation endpoint returned markdown-formatted output.")

        try:
            structured = json.loads(content)
        except (ValueError, TypeError) as exc:
            raise LanguageServiceError("The configured translation endpoint returned non-JSON content.") from exc

        if not isinstance(structured, dict):
            raise LanguageServiceError("The configured translation endpoint returned a non-object JSON value.")

        try:
            payload = TranslationQueryPayload.model_validate(structured)
        except pydantic.ValidationError as exc:
            raise LanguageServiceError(
                "The configured translation endpoint returned a response that failed structural validation."
            ) from exc

        if detect_language(payload.query) == DetectedLanguage.HE:
            raise LanguageServiceError("The configured translation endpoint did not actually translate the query.")

        return payload.query
