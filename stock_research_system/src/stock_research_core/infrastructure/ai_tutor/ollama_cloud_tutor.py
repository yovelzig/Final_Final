"""Native Ollama Cloud tutor-model adapter, satisfying `TutorModelPort`.

Calls Ollama Cloud's own `POST {base_url}/chat` endpoint directly (not the
OpenAI-compatible `/v1/chat/completions` shape used by
`OpenAICompatibleTutorAdapter`) - see spec Phase D. Tests must inject an
`httpx.AsyncClient` built with a mock transport (`httpx.MockTransport` /
`httpx.ASGITransport`) - this adapter never requires real network access to
be unit-tested, and it never makes a live call during the unit suite.

`message.thinking` (Ollama Cloud's optional chain-of-thought field) is read
by nothing here: only `message.content` is parsed. It is never logged,
persisted, exposed, or returned in a `TutorModelResult`.

Response parsing is defensive by construction (spec G2D2 section 2):
extra top-level keys, an oversized `cited_chunk_ids` list, or an
oversized `answer_markdown` are all rejected exactly like malformed
JSON - one bounded repair attempt, then a `TutorModelProviderError`.
Citations are read only from the structured `cited_chunk_ids` field,
never inferred from prose in `answer_markdown`.
"""

from __future__ import annotations

import asyncio
import json
import time
from uuid import UUID

import httpx

from stock_research_core.application.ai_tutor.diagnostics import TutorDiagnosticIssueCode, log_tutor_diagnostic
from stock_research_core.application.ai_tutor.models import TutorModelRequest, TutorModelResult
from stock_research_core.application.exceptions import TutorModelProviderError
from stock_research_core.domain.ai_tutor.enums import TutorProviderType

DEFAULT_OLLAMA_CLOUD_BASE_URL = "https://ollama.com/api"

_MAX_TRANSIENT_RETRIES = 2
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})

# Defensive bounds on the parsed structured response (spec G2D2 section
# 2: "reject extra/unbounded data") - independent of anything the
# retrieved-candidate set itself already bounds, so a pathological
# response can never be accepted purely because every individual cited
# id happens to be valid.
_ALLOWED_RESPONSE_KEYS = frozenset({"answer_markdown", "cited_chunk_ids"})
_MAX_CITED_CHUNK_IDS = 50
_MAX_ANSWER_MARKDOWN_CHARACTERS = 20_000

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


class OllamaCloudTutorAdapter:
    """Calls Ollama Cloud's native chat endpoint. Satisfies `TutorModelPort`."""

    provider_type = TutorProviderType.OLLAMA_CLOUD

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_OLLAMA_CLOUD_BASE_URL,
        api_key: str,
        model_name: str,
        timeout_seconds: float = 60.0,
        thinking_level: str = "low",
        client: httpx.AsyncClient | None = None,
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

    async def generate(self, request: TutorModelRequest) -> TutorModelResult:
        valid_chunk_ids = {candidate.chunk.chunk_id for candidate in request.retrieved_candidates}
        candidate_count = len(request.retrieved_candidates)
        started_at = time.monotonic()

        raw_response = await self._call_model(request, extra_instructions=None)
        parsed = self._parse_response(raw_response, valid_chunk_ids)
        if parsed is not None:
            answer_markdown, cited_chunk_ids, response_id = parsed
            self._log_attempt(
                attempt_number=1, candidate_count=candidate_count, cited_id_count=len(cited_chunk_ids),
                issue_codes=[], started_at=started_at,
            )
            return TutorModelResult(
                answer_markdown=answer_markdown,
                cited_chunk_ids=cited_chunk_ids,
                provider_type=self.provider_type,
                model_name=self._model_name,
                model_response_id=response_id,
            )

        first_attempt_issue = self._classify_failure(raw_response, valid_chunk_ids)
        self._log_attempt(
            attempt_number=1, candidate_count=candidate_count, cited_id_count=0,
            issue_codes=[first_attempt_issue], started_at=started_at,
        )

        # One bounded correction attempt on a structured-output validation failure.
        raw_response = await self._call_model(request, extra_instructions=_VALIDATION_RETRY_INSTRUCTIONS)
        parsed = self._parse_response(raw_response, valid_chunk_ids)
        if parsed is None:
            second_attempt_issue = self._classify_failure(raw_response, valid_chunk_ids)
            self._log_attempt(
                attempt_number=2, candidate_count=candidate_count, cited_id_count=0,
                issue_codes=[second_attempt_issue, TutorDiagnosticIssueCode.REPAIR_ATTEMPT_FAILED],
                started_at=started_at,
            )
            raise TutorModelProviderError(
                "The configured tutor model did not return a valid structured answer after one "
                "correction attempt."
            )
        answer_markdown, cited_chunk_ids, response_id = parsed
        self._log_attempt(
            attempt_number=2, candidate_count=candidate_count, cited_id_count=len(cited_chunk_ids),
            issue_codes=[], started_at=started_at,
        )
        return TutorModelResult(
            answer_markdown=answer_markdown,
            cited_chunk_ids=cited_chunk_ids,
            provider_type=self.provider_type,
            model_name=self._model_name,
            model_response_id=response_id,
        )

    def _log_attempt(
        self, *, attempt_number: int, candidate_count: int, cited_id_count: int, issue_codes: list[str],
        started_at: float,
    ) -> None:
        log_tutor_diagnostic(
            provider_type=self.provider_type,
            model_name=self._model_name,
            attempt_number=attempt_number,
            retrieval_candidate_count=candidate_count,
            cited_id_count=cited_id_count,
            issue_codes=issue_codes,
            elapsed_ms=(time.monotonic() - started_at) * 1000,
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
            "stream": False,
            "think": self._thinking_level,
            "options": {
                "temperature": 0,
                "num_predict": request.maximum_output_tokens or self._maximum_output_tokens,
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
                issue = (
                    TutorDiagnosticIssueCode.MODEL_TIMEOUT
                    if isinstance(exc, httpx.TimeoutException)
                    else TutorDiagnosticIssueCode.PROVIDER_ERROR
                )
                log_tutor_diagnostic(
                    provider_type=self.provider_type, model_name=self._model_name, attempt_number=attempt + 1,
                    retrieval_candidate_count=len(request.retrieved_candidates), cited_id_count=0,
                    issue_codes=[issue],
                )
                raise TutorModelProviderError(
                    "The configured tutor model endpoint was unreachable after retrying."
                ) from exc

            if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_TRANSIENT_RETRIES:
                last_error = TutorModelProviderError(f"Transient HTTP {response.status_code} from tutor model")
                await asyncio.sleep(0)
                continue

            if response.status_code >= 400:
                log_tutor_diagnostic(
                    provider_type=self.provider_type, model_name=self._model_name, attempt_number=attempt + 1,
                    retrieval_candidate_count=len(request.retrieved_candidates), cited_id_count=0,
                    issue_codes=[TutorDiagnosticIssueCode.PROVIDER_ERROR],
                )
                raise TutorModelProviderError(
                    f"The configured tutor model endpoint returned HTTP {response.status_code}."
                )

            try:
                return response.json()
            except ValueError as exc:
                raise TutorModelProviderError(
                    "The configured tutor model endpoint returned a non-JSON response."
                ) from exc

        log_tutor_diagnostic(
            provider_type=self.provider_type, model_name=self._model_name, attempt_number=_MAX_TRANSIENT_RETRIES + 1,
            retrieval_candidate_count=len(request.retrieved_candidates), cited_id_count=0,
            issue_codes=[TutorDiagnosticIssueCode.PROVIDER_ERROR],
        )
        raise TutorModelProviderError(
            "The configured tutor model endpoint was unreachable after retrying."
        ) from last_error

    def _extract_structured_content(self, raw_response: dict) -> dict | None:
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

    def _parse_response(
        self, raw_response: dict, valid_chunk_ids: set[UUID]
    ) -> tuple[str, list[UUID], str | None] | None:
        structured = self._extract_structured_content(raw_response)
        if structured is None:
            return None

        answer_markdown = structured.get("answer_markdown")
        raw_cited_ids = structured.get("cited_chunk_ids")
        if not isinstance(answer_markdown, str) or not answer_markdown.strip():
            return None
        if len(answer_markdown) > _MAX_ANSWER_MARKDOWN_CHARACTERS:
            return None
        if not isinstance(raw_cited_ids, list):
            return None
        if len(raw_cited_ids) > _MAX_CITED_CHUNK_IDS:
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

        response_id = raw_response.get("created_at")
        return answer_markdown, cited_chunk_ids, str(response_id) if response_id is not None else None

    def _classify_failure(self, raw_response: dict, valid_chunk_ids: set[UUID]) -> str:
        """Diagnostics-only classification, never used for control flow -
        `_parse_response` above remains the single source of truth for
        whether a response is accepted."""
        try:
            content = raw_response["message"]["content"]
            if not isinstance(content, str):
                return TutorDiagnosticIssueCode.MALFORMED_MODEL_RESPONSE
            structured = json.loads(content)
        except (KeyError, TypeError, ValueError):
            return TutorDiagnosticIssueCode.MALFORMED_MODEL_RESPONSE

        if not isinstance(structured, dict):
            return TutorDiagnosticIssueCode.MALFORMED_MODEL_RESPONSE
        if not set(structured.keys()) <= _ALLOWED_RESPONSE_KEYS:
            return TutorDiagnosticIssueCode.OUTPUT_SCHEMA_VIOLATION

        raw_cited_ids = structured.get("cited_chunk_ids")
        if not isinstance(raw_cited_ids, list) or len(raw_cited_ids) > _MAX_CITED_CHUNK_IDS:
            return TutorDiagnosticIssueCode.OUTPUT_SCHEMA_VIOLATION
        for raw_id in raw_cited_ids:
            try:
                chunk_id = UUID(str(raw_id))
            except (ValueError, AttributeError, TypeError):
                return TutorDiagnosticIssueCode.MALFORMED_MODEL_RESPONSE
            if chunk_id not in valid_chunk_ids:
                return TutorDiagnosticIssueCode.INVALID_CITATION_CHUNK_ID

        return TutorDiagnosticIssueCode.MALFORMED_MODEL_RESPONSE
