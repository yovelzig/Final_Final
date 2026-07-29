"""Native Ollama Cloud research-synthesis adapter, satisfying
`ResearchModelPort` (spec G2D2/H1 correction pass, section 6).

Calls Ollama Cloud's own `POST {base_url}/chat` endpoint directly - the
same access pattern `OllamaCloudTutorAdapter` uses for the Tutor path,
but deliberately a separate class: this one is typed to
`ResearchSynthesisRequest`/`ResearchSynthesisResult` and the
`EvidenceItem`-scoped `cited_evidence_ids` field, never Tutor chunk ids.
No tools, no web search - the model only ever sees the bounded evidence
excerpts already included in the prompt.

Response parsing is defensive: extra top-level keys, an oversized
`cited_evidence_ids` list, or an oversized `answer_markdown` are all
rejected exactly like malformed JSON - one bounded retry, then a
`ResearchModelProviderError`. Citation membership (does a cited id
actually belong to *this* verified `ResearchRun`) is deliberately NOT
enforced here - that is `ResearchEvidenceCitationVerifier`'s job,
against a fresh PostgreSQL read, not this adapter's own request-scoped
evidence list.
"""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

import httpx

from stock_research_core.application.exceptions import ResearchModelProviderError
from stock_research_core.application.live_research.synthesis_models import (
    ResearchModelProviderType,
    ResearchSynthesisRequest,
    ResearchSynthesisResult,
)

DEFAULT_OLLAMA_CLOUD_BASE_URL = "https://ollama.com/api"

_MAX_TRANSIENT_RETRIES = 2
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})

_ALLOWED_RESPONSE_KEYS = frozenset({"answer_markdown", "cited_evidence_ids"})
_MAX_CITED_EVIDENCE_IDS = 50
_MAX_ANSWER_MARKDOWN_CHARACTERS = 20_000

_RESPONSE_FORMAT_INSTRUCTIONS = (
    'Respond with a single JSON object of exactly this shape, and nothing else: '
    '{"answer_markdown": "string", "cited_evidence_ids": ["UUID", ...]}. '
    "Never use a tool, never browse the web, never invent a source - cite only evidence ids from the "
    "evidence provided below."
)

_VALIDATION_RETRY_INSTRUCTIONS = (
    "Your previous response was not valid JSON matching the required "
    '{"answer_markdown": "string", "cited_evidence_ids": ["UUID", ...]} shape. Respond again with only '
    "that exact JSON object."
)


def _format_evidence_block(request: ResearchSynthesisRequest) -> str:
    lines = ["Evidence:"]
    for item in request.evidence_items:
        official_tag = " (official source)" if item.official else ""
        lines.append(f"- id={item.evidence_id} | {item.source_title} ({item.publisher}){official_tag}: {item.excerpt}")
    return "\n".join(lines)


class OllamaResearchSynthesisAdapter:
    """Calls Ollama Cloud's native chat endpoint. Satisfies `ResearchModelPort`."""

    provider_type = ResearchModelProviderType.OLLAMA_CLOUD

    def __init__(
        self, *, base_url: str = DEFAULT_OLLAMA_CLOUD_BASE_URL, api_key: str, model_name: str,
        timeout_seconds: float = 60.0, thinking_level: str = "low", client: httpx.AsyncClient | None = None,
        maximum_output_tokens: int = 800,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_name = model_name
        self._timeout_seconds = timeout_seconds
        self._thinking_level = thinking_level
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._maximum_output_tokens = maximum_output_tokens

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def generate(self, request: ResearchSynthesisRequest) -> ResearchSynthesisResult:
        raw_response = await self._call_model(request, extra_instructions=None)
        parsed = self._parse_response(raw_response)
        if parsed is None:
            raw_response = await self._call_model(request, extra_instructions=_VALIDATION_RETRY_INSTRUCTIONS)
            parsed = self._parse_response(raw_response)
        if parsed is None:
            raise ResearchModelProviderError(
                "The configured research synthesis model did not return a valid structured answer "
                "after one correction attempt."
            )
        answer_markdown, cited_evidence_ids, response_id = parsed
        return ResearchSynthesisResult(
            answer_markdown=answer_markdown, cited_evidence_ids=cited_evidence_ids,
            provider_type=self.provider_type, model_name=self._model_name, model_response_id=response_id,
        )

    async def _call_model(self, request: ResearchSynthesisRequest, *, extra_instructions: str | None) -> dict:
        system_content = request.system_instructions + "\n" + _RESPONSE_FORMAT_INSTRUCTIONS
        user_content = request.user_question + "\n\n" + _format_evidence_block(request)
        if extra_instructions:
            user_content = f"{user_content}\n\n{extra_instructions}"
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]
        payload = {
            "model": self._model_name, "messages": messages, "stream": False, "think": self._thinking_level,
            "options": {
                "temperature": 0, "num_predict": request.maximum_output_tokens or self._maximum_output_tokens,
            },
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        last_error: Exception | None = None
        for attempt in range(_MAX_TRANSIENT_RETRIES + 1):
            try:
                response = await self._client.post(f"{self._base_url}/chat", json=payload, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt < _MAX_TRANSIENT_RETRIES:
                    await asyncio.sleep(0)
                    continue
                raise ResearchModelProviderError(
                    "The configured research synthesis model endpoint was unreachable after retrying."
                ) from exc

            if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_TRANSIENT_RETRIES:
                last_error = ResearchModelProviderError(f"Transient HTTP {response.status_code}")
                await asyncio.sleep(0)
                continue

            if response.status_code >= 400:
                raise ResearchModelProviderError(
                    f"The configured research synthesis model endpoint returned HTTP {response.status_code}."
                )

            try:
                return response.json()
            except ValueError as exc:
                raise ResearchModelProviderError(
                    "The configured research synthesis model endpoint returned a non-JSON response."
                ) from exc

        raise ResearchModelProviderError(
            "The configured research synthesis model endpoint was unreachable after retrying."
        ) from last_error

    @staticmethod
    def _extract_structured_content(raw_response: dict) -> dict | None:
        try:
            content = raw_response["message"]["content"]
        except (KeyError, TypeError):
            return None
        if not isinstance(content, str):
            return None
        try:
            structured = json.loads(content)
        except (ValueError, TypeError):
            return None
        if not isinstance(structured, dict):
            return None
        if not set(structured.keys()) <= _ALLOWED_RESPONSE_KEYS:
            return None
        return structured

    def _parse_response(self, raw_response: dict) -> tuple[str, list[UUID], str | None] | None:
        structured = self._extract_structured_content(raw_response)
        if structured is None:
            return None

        answer_markdown = structured.get("answer_markdown")
        raw_cited_ids = structured.get("cited_evidence_ids")
        if not isinstance(answer_markdown, str) or not answer_markdown.strip():
            return None
        if len(answer_markdown) > _MAX_ANSWER_MARKDOWN_CHARACTERS:
            return None
        if not isinstance(raw_cited_ids, list) or len(raw_cited_ids) > _MAX_CITED_EVIDENCE_IDS:
            return None

        cited_evidence_ids: list[UUID] = []
        for raw_id in raw_cited_ids:
            try:
                evidence_id = UUID(str(raw_id))
            except (ValueError, AttributeError, TypeError):
                return None
            if evidence_id not in cited_evidence_ids:
                cited_evidence_ids.append(evidence_id)

        response_id = raw_response.get("created_at")
        return answer_markdown, cited_evidence_ids, str(response_id) if response_id is not None else None
