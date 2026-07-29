"""Optional OpenAI research-synthesis adapter, satisfying
`ResearchModelPort` (spec G2D2/H1 correction pass, section 6).

Uses the official `openai` SDK's `AsyncOpenAI.responses.create(...)`
(Responses API) with a strict JSON-schema structured output of exactly
`{answer_markdown, cited_evidence_ids}` - `tools=[]` (no web search, no
file search, no code execution, no MCP/function/agent tools), so the
model can never fetch its own "evidence" outside the bounded excerpts it
was given. Disabled by default; only constructed by the composition root
when the research-synthesis OpenAI secondary is explicitly enabled.

`openai` is imported lazily inside `_get_client()`/`generate()` (mirrors
`OpenAIReasoningTutorAdapter`'s own convention) so this module can be
imported freely without requiring the dependency to be importable in
every environment, and never does any network setup at import time.
"""

from __future__ import annotations

import json
from uuid import UUID

from stock_research_core.application.exceptions import ResearchModelProviderError
from stock_research_core.application.live_research.synthesis_models import (
    ResearchModelProviderType,
    ResearchSynthesisRequest,
    ResearchSynthesisResult,
)

_RESPONSE_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer_markdown", "cited_evidence_ids"],
    "properties": {
        "answer_markdown": {"type": "string"},
        "cited_evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
}

_MAX_CITED_EVIDENCE_IDS = 50
_MAX_ANSWER_MARKDOWN_CHARACTERS = 20_000


def _format_evidence_block(request: ResearchSynthesisRequest) -> str:
    lines = ["Evidence:"]
    for item in request.evidence_items:
        official_tag = " (official source)" if item.official else ""
        lines.append(f"- id={item.evidence_id} | {item.source_title} ({item.publisher}){official_tag}: {item.excerpt}")
    return "\n".join(lines)


class OpenAIResearchSynthesisAdapter:
    """Calls OpenAI's Responses API with strict structured output. Satisfies `ResearchModelPort`."""

    provider_type = ResearchModelProviderType.OPENAI_REASONING

    def __init__(
        self, *, api_key: str, model_name: str, timeout_seconds: float = 45.0, maximum_output_tokens: int = 2000,
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

    async def generate(self, request: ResearchSynthesisRequest) -> ResearchSynthesisResult:
        client = self._get_client()

        instructions = request.system_instructions + (
            "\n\nRespond only with the structured JSON output described by the response schema. "
            "Never use a tool, never browse the web, never invent a source. Cite only evidence ids from "
            "the evidence provided in the input."
        )
        input_text = request.user_question + "\n\n" + _format_evidence_block(request)

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
                        "name": "research_synthesis_answer",
                        "schema": _RESPONSE_JSON_SCHEMA,
                        "strict": True,
                    }
                },
            )
        except APITimeoutError as exc:
            raise ResearchModelProviderError("The OpenAI research synthesis model timed out.") from exc
        except APIError as exc:
            raise ResearchModelProviderError("The OpenAI research synthesis model returned an error.") from exc

        parsed = self._parse_response(response)
        if parsed is None:
            raise ResearchModelProviderError(
                "The OpenAI research synthesis model did not return a valid structured answer."
            )

        answer_markdown, cited_evidence_ids, response_id = parsed
        return ResearchSynthesisResult(
            answer_markdown=answer_markdown, cited_evidence_ids=cited_evidence_ids,
            provider_type=self.provider_type, model_name=self._model_name, model_response_id=response_id,
        )

    @staticmethod
    def _parse_response(response: object) -> tuple[str, list[UUID], str | None] | None:
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            return None
        try:
            structured = json.loads(output_text)
        except (ValueError, TypeError):
            return None
        if not isinstance(structured, dict):
            return None
        if not set(structured.keys()) <= {"answer_markdown", "cited_evidence_ids"}:
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

        response_id = getattr(response, "id", None)
        return answer_markdown, cited_evidence_ids, str(response_id) if response_id is not None else None
