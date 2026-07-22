"""OpenAI-compatible HTTP tutor-model adapter, satisfying `TutorModelPort`.

Talks to any OpenAI-compatible chat-completions endpoint (a local
Ollama `/v1` endpoint, vLLM, or a remote compatible provider) -
configuration only, never a hard-coded commercial provider. Tests must
inject an `httpx.AsyncClient` built with a mock transport
(`httpx.MockTransport` / `httpx.ASGITransport`) - this adapter never
requires real network access to be unit-tested.
"""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

import httpx

from stock_research_core.application.ai_tutor.models import TutorModelRequest, TutorModelResult
from stock_research_core.application.exceptions import TutorModelProviderError
from stock_research_core.domain.ai_tutor.enums import TutorProviderType

_MAX_TRANSIENT_RETRIES = 2
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})

_RESPONSE_FORMAT_INSTRUCTIONS = (
    'Respond with a single JSON object of exactly this shape, and nothing else: '
    '{"answer_markdown": "string", "cited_chunk_ids": ["UUID", ...]}'
)

_VALIDATION_RETRY_INSTRUCTIONS = (
    "Your previous response was not valid JSON matching the required "
    '{"answer_markdown": "string", "cited_chunk_ids": ["UUID", ...]} shape, or cited a chunk ID that '
    "was not in the retrieved evidence. Respond again with only that exact JSON object, citing only "
    "chunk IDs from the 'Valid cited_chunk_ids for this question' list."
)


class OpenAICompatibleTutorAdapter:
    """Calls a configured OpenAI-compatible chat-completions endpoint. Satisfies `TutorModelPort`."""

    provider_type = TutorProviderType.OPENAI_COMPATIBLE

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        timeout_seconds: float = 60.0,
        client: httpx.AsyncClient | None = None,
        maximum_output_tokens: int = 800,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_name = model_name
        self._timeout_seconds = timeout_seconds
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._maximum_output_tokens = maximum_output_tokens

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def generate(self, request: TutorModelRequest) -> TutorModelResult:
        valid_chunk_ids = {candidate.chunk.chunk_id for candidate in request.retrieved_candidates}

        raw_response = await self._call_model(request, extra_instructions=None)
        parsed = self._parse_response(raw_response, valid_chunk_ids)
        if parsed is not None:
            answer_markdown, cited_chunk_ids, response_id = parsed
            return TutorModelResult(
                answer_markdown=answer_markdown,
                cited_chunk_ids=cited_chunk_ids,
                provider_type=self.provider_type,
                model_name=self._model_name,
                model_response_id=response_id,
            )

        # One bounded correction attempt on a structured-output validation failure.
        raw_response = await self._call_model(request, extra_instructions=_VALIDATION_RETRY_INSTRUCTIONS)
        parsed = self._parse_response(raw_response, valid_chunk_ids)
        if parsed is None:
            raise TutorModelProviderError(
                "The configured tutor model did not return a valid structured answer after one "
                "correction attempt."
            )
        answer_markdown, cited_chunk_ids, response_id = parsed
        return TutorModelResult(
            answer_markdown=answer_markdown,
            cited_chunk_ids=cited_chunk_ids,
            provider_type=self.provider_type,
            model_name=self._model_name,
            model_response_id=response_id,
        )

    async def _call_model(self, request: TutorModelRequest, *, extra_instructions: str | None) -> dict:
        system_content = request.system_instructions + "\n" + _RESPONSE_FORMAT_INSTRUCTIONS
        messages = [{"role": "system", "content": system_content}]
        for message in request.conversation_messages:
            role = "assistant" if message.role.value == "ASSISTANT" else "user"
            messages.append({"role": role, "content": message.content})
        user_content = request.user_question
        if extra_instructions:
            user_content = f"{user_content}\n\n{extra_instructions}"
        messages.append({"role": "user", "content": user_content})

        payload = {
            "model": self._model_name,
            "messages": messages,
            "max_tokens": request.maximum_output_tokens or self._maximum_output_tokens,
            "temperature": 0,
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        last_error: Exception | None = None
        for attempt in range(_MAX_TRANSIENT_RETRIES + 1):
            try:
                response = await self._client.post(
                    f"{self._base_url}/chat/completions", json=payload, headers=headers
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt < _MAX_TRANSIENT_RETRIES:
                    await asyncio.sleep(0)
                    continue
                raise TutorModelProviderError(
                    "The configured tutor model endpoint was unreachable after retrying."
                ) from exc

            if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_TRANSIENT_RETRIES:
                last_error = TutorModelProviderError(f"Transient HTTP {response.status_code} from tutor model")
                await asyncio.sleep(0)
                continue

            if response.status_code >= 400:
                raise TutorModelProviderError(
                    f"The configured tutor model endpoint returned HTTP {response.status_code}."
                )

            try:
                return response.json()
            except ValueError as exc:
                raise TutorModelProviderError(
                    "The configured tutor model endpoint returned a non-JSON response."
                ) from exc

        raise TutorModelProviderError(
            "The configured tutor model endpoint was unreachable after retrying."
        ) from last_error

    def _parse_response(
        self, raw_response: dict, valid_chunk_ids: set[UUID]
    ) -> tuple[str, list[UUID], str | None] | None:
        try:
            choices = raw_response["choices"]
            content = choices[0]["message"]["content"]
            response_id = raw_response.get("id")
        except (KeyError, IndexError, TypeError):
            return None

        try:
            structured = json.loads(content)
        except (ValueError, TypeError):
            return None

        if not isinstance(structured, dict):
            return None
        answer_markdown = structured.get("answer_markdown")
        raw_cited_ids = structured.get("cited_chunk_ids")
        if not isinstance(answer_markdown, str) or not answer_markdown.strip():
            return None
        if not isinstance(raw_cited_ids, list):
            return None

        cited_chunk_ids: list[UUID] = []
        for raw_id in raw_cited_ids:
            try:
                chunk_id = UUID(str(raw_id))
            except (ValueError, AttributeError, TypeError):
                return None
            if chunk_id not in valid_chunk_ids:
                return None
            if chunk_id not in cited_chunk_ids:
                cited_chunk_ids.append(chunk_id)

        return answer_markdown, cited_chunk_ids, str(response_id) if response_id is not None else None
