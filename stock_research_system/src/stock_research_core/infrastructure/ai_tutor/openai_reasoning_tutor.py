"""Optional OpenAI reasoning tutor-model adapter, satisfying
`TutorModelPort` (spec G2D2 section 5/10).

Uses the official `openai` SDK's `AsyncOpenAI.responses.create(...)`
(Responses API) with a strict JSON-schema structured output of exactly
`{answer_markdown, cited_chunk_ids}` - no tools configured (no web
search, file search, code execution, MCP, function, or agent tools), so
the model can never fetch its own "evidence" outside the retrieved
candidates it was given. Disabled by default; only constructed by the
composition root when `OPENAI_REASONING_ENABLED=true`.

`openai` is imported lazily inside `generate()` (mirroring
`ragas_model_factory.build_ragas_llm`'s lazy-import convention) so this
module can be imported freely without requiring the dependency to be
importable in every environment, and so it never does any network setup
at import time.
"""

from __future__ import annotations

import time
from uuid import UUID

from stock_research_core.application.ai_tutor.diagnostics import TutorDiagnosticIssueCode, log_tutor_diagnostic
from stock_research_core.application.ai_tutor.models import TutorModelRequest, TutorModelResult
from stock_research_core.application.exceptions import TutorModelProviderError
from stock_research_core.domain.ai_tutor.enums import TutorProviderType

_RESPONSE_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer_markdown", "cited_chunk_ids"],
    "properties": {
        "answer_markdown": {"type": "string"},
        "cited_chunk_ids": {"type": "array", "items": {"type": "string"}},
    },
}

_MAX_CITED_CHUNK_IDS = 50
_MAX_ANSWER_MARKDOWN_CHARACTERS = 20_000


class OpenAIReasoningTutorAdapter:
    """Calls OpenAI's Responses API with strict structured output. Satisfies `TutorModelPort`."""

    provider_type = TutorProviderType.OPENAI_REASONING

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        timeout_seconds: float = 45.0,
        maximum_output_tokens: int = 2000,
        client: object | None = None,
    ) -> None:
        self._api_key = api_key
        self._model_name = model_name
        self._timeout_seconds = timeout_seconds
        self._maximum_output_tokens = maximum_output_tokens
        self._owns_client = client is None
        self._client = client

    def _get_client(self):
        if self._client is not None:
            return self._client
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=self._api_key, timeout=self._timeout_seconds, max_retries=0)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.close()

    async def generate(self, request: TutorModelRequest) -> TutorModelResult:
        valid_chunk_ids = {candidate.chunk.chunk_id for candidate in request.retrieved_candidates}
        started_at = time.monotonic()
        client = self._get_client()

        instructions = request.system_instructions + (
            "\n\nRespond only with the structured JSON output described by the response schema. "
            "Never use a tool, never browse the web, never invent a source. Cite only chunk ids from "
            "the retrieved candidates provided in the input."
        )
        input_text = request.user_question

        from openai import APIError, APITimeoutError

        try:
            response = await client.responses.create(
                model=self._model_name,
                instructions=instructions,
                input=input_text,
                max_output_tokens=request.maximum_output_tokens or self._maximum_output_tokens,
                tools=[],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "tutor_answer",
                        "schema": _RESPONSE_JSON_SCHEMA,
                        "strict": True,
                    }
                },
            )
        except APITimeoutError as exc:
            log_tutor_diagnostic(
                provider_type=self.provider_type, model_name=self._model_name, attempt_number=1,
                retrieval_candidate_count=len(request.retrieved_candidates), cited_id_count=0,
                issue_codes=[TutorDiagnosticIssueCode.MODEL_TIMEOUT],
                elapsed_ms=(time.monotonic() - started_at) * 1000,
            )
            raise TutorModelProviderError("The OpenAI reasoning tutor model timed out.") from exc
        except APIError as exc:
            log_tutor_diagnostic(
                provider_type=self.provider_type, model_name=self._model_name, attempt_number=1,
                retrieval_candidate_count=len(request.retrieved_candidates), cited_id_count=0,
                issue_codes=[TutorDiagnosticIssueCode.PROVIDER_ERROR],
                elapsed_ms=(time.monotonic() - started_at) * 1000,
            )
            raise TutorModelProviderError("The OpenAI reasoning tutor model returned an error.") from exc

        parsed = self._parse_response(response, valid_chunk_ids)
        if parsed is None:
            log_tutor_diagnostic(
                provider_type=self.provider_type, model_name=self._model_name, attempt_number=1,
                retrieval_candidate_count=len(request.retrieved_candidates), cited_id_count=0,
                issue_codes=[TutorDiagnosticIssueCode.MALFORMED_MODEL_RESPONSE],
                elapsed_ms=(time.monotonic() - started_at) * 1000,
            )
            # OPENAI_REASONING_MAX_ATTEMPTS=1 (spec G2D2 section 10): no
            # repair attempt here - a malformed response fails closed
            # immediately, unlike the Ollama adapter's one-retry shape.
            raise TutorModelProviderError(
                "The OpenAI reasoning tutor model did not return a valid structured answer."
            )

        answer_markdown, cited_chunk_ids, response_id = parsed
        log_tutor_diagnostic(
            provider_type=self.provider_type, model_name=self._model_name, attempt_number=1,
            retrieval_candidate_count=len(request.retrieved_candidates), cited_id_count=len(cited_chunk_ids),
            elapsed_ms=(time.monotonic() - started_at) * 1000,
        )
        return TutorModelResult(
            answer_markdown=answer_markdown,
            cited_chunk_ids=cited_chunk_ids,
            provider_type=self.provider_type,
            model_name=self._model_name,
            model_response_id=response_id,
        )

    def _parse_response(
        self, response: object, valid_chunk_ids: set[UUID]
    ) -> tuple[str, list[UUID], str | None] | None:
        import json

        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            return None
        try:
            structured = json.loads(output_text)
        except (ValueError, TypeError):
            return None
        if not isinstance(structured, dict):
            return None
        if not set(structured.keys()) <= {"answer_markdown", "cited_chunk_ids"}:
            return None

        answer_markdown = structured.get("answer_markdown")
        raw_cited_ids = structured.get("cited_chunk_ids")
        if not isinstance(answer_markdown, str) or not answer_markdown.strip():
            return None
        if len(answer_markdown) > _MAX_ANSWER_MARKDOWN_CHARACTERS:
            return None
        if not isinstance(raw_cited_ids, list) or len(raw_cited_ids) > _MAX_CITED_CHUNK_IDS:
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

        response_id = getattr(response, "id", None)
        return answer_markdown, cited_chunk_ids, str(response_id) if response_id is not None else None
