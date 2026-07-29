"""Unit tests for `OpenAIReasoningTutorAdapter` (spec G2D2 section 10).

Every request goes through an injected fake client exposing
`.responses.create(...)` - no real network access and no live call to
OpenAI is ever made in this file. `openai.APIError`/`APITimeoutError`
are constructed directly to simulate provider failures.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from openai import APIError, APITimeoutError

from stock_research_core.application.ai_tutor.models import RetrievalCandidate, TutorModelRequest
from stock_research_core.application.exceptions import TutorModelProviderError
from stock_research_core.domain.ai_tutor.enums import (
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeSourceType,
    TutorProviderType,
)
from stock_research_core.domain.ai_tutor.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from stock_research_core.infrastructure.ai_tutor.openai_reasoning_tutor import OpenAIReasoningTutorAdapter

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_HASH = hashlib.sha256(b"x").hexdigest()
_FAKE_API_KEY = "sk-test-only-not-a-real-secret-abc123"


def _candidate(content: str = "Compound interest grows a period's balance.") -> RetrievalCandidate:
    source = KnowledgeSource(
        source_type=KnowledgeSourceType.LOCAL_MARKDOWN, title="Approved Source",
        approval_status=KnowledgeApprovalStatus.APPROVED,
    )
    document = KnowledgeDocument(
        source_id=source.source_id, title="Doc", content_text=content, content_hash=_HASH,
        status=KnowledgeDocumentStatus.PROCESSED, approval_status=KnowledgeApprovalStatus.APPROVED,
        available_at=NOW, parser_version="v1",
    )
    chunk = KnowledgeChunk(
        document_id=document.document_id, chunk_index=0, content=content, content_hash=_HASH,
        word_count=len(content.split()), estimated_token_count=len(content.split()) + 2,
        available_at=NOW, chunking_version="heading-word-chunker-v1",
    )
    return RetrievalCandidate(chunk=chunk, source=source, document=document, metadata_score=0.5, combined_score=0.5)


def _request(
    candidates: list[RetrievalCandidate] | None = None, question: str = "What is compound interest?"
) -> TutorModelRequest:
    return TutorModelRequest(
        system_instructions="You are a grounded, careful financial-education tutor.",
        user_question=question, conversation_messages=[], retrieved_candidates=candidates or [],
        prompt_version="v1",
    )


def _response(*, answer: str = "The answer.", cited_ids: list[str] | None = None, response_id: str = "resp_1"):
    output_text = json.dumps({"answer_markdown": answer, "cited_chunk_ids": cited_ids or []})
    return SimpleNamespace(output_text=output_text, id=response_id)


class _FakeResponses:
    def __init__(self, results: list) -> None:
        self._results = results
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self._results[len(self.calls) - 1]
        if isinstance(result, Exception):
            raise result
        return result


class _FakeClient:
    def __init__(self, results: list) -> None:
        self.responses = _FakeResponses(results)


def _make_adapter(results: list, **overrides) -> tuple[OpenAIReasoningTutorAdapter, _FakeClient]:
    client = _FakeClient(results)
    kwargs = {"api_key": _FAKE_API_KEY, "model_name": "gpt-5-reasoning", "client": client}
    kwargs.update(overrides)
    return OpenAIReasoningTutorAdapter(**kwargs), client


class TestRequestShape:
    async def test_no_tools_configured(self) -> None:
        adapter, client = _make_adapter([_response()])
        await adapter.generate(_request())
        assert client.responses.calls[0]["tools"] == []

    async def test_strict_json_schema_requested(self) -> None:
        adapter, client = _make_adapter([_response()])
        await adapter.generate(_request())
        text_config = client.responses.calls[0]["text"]
        assert text_config["format"]["type"] == "json_schema"
        assert text_config["format"]["strict"] is True

    async def test_model_and_max_output_tokens_forwarded(self) -> None:
        adapter, client = _make_adapter([_response()])
        request = _request().model_copy(update={"maximum_output_tokens": 1234})
        await adapter.generate(request)
        assert client.responses.calls[0]["model"] == "gpt-5-reasoning"
        assert client.responses.calls[0]["max_output_tokens"] == 1234


class TestSuccessfulResponses:
    async def test_valid_response_parsed(self) -> None:
        adapter, _ = _make_adapter([_response(answer="The answer.")])
        result = await adapter.generate(_request())
        assert result.answer_markdown == "The answer."
        assert result.provider_type == TutorProviderType.OPENAI_REASONING
        assert result.model_name == "gpt-5-reasoning"

    async def test_valid_citations_converted_to_uuids(self) -> None:
        candidate = _candidate()
        chunk_id = str(candidate.chunk.chunk_id)
        adapter, _ = _make_adapter([_response(cited_ids=[chunk_id])])
        result = await adapter.generate(_request(candidates=[candidate]))
        assert result.cited_chunk_ids == [candidate.chunk.chunk_id]
        assert isinstance(result.cited_chunk_ids[0], UUID)


class TestNoRepairAttempt:
    """OPENAI_REASONING_MAX_ATTEMPTS=1 (spec section 10) - unlike the
    Ollama adapter, a malformed response fails closed on the first
    attempt, never triggering a second call."""

    async def test_invalid_json_fails_without_a_second_call(self) -> None:
        adapter, client = _make_adapter([SimpleNamespace(output_text="not json", id="r1")])
        with pytest.raises(TutorModelProviderError):
            await adapter.generate(_request())
        assert len(client.responses.calls) == 1

    async def test_unknown_citation_fails_without_a_second_call(self) -> None:
        candidate = _candidate()
        adapter, client = _make_adapter([_response(cited_ids=[str(uuid4())])])
        with pytest.raises(TutorModelProviderError):
            await adapter.generate(_request(candidates=[candidate]))
        assert len(client.responses.calls) == 1

    async def test_extra_top_level_key_is_rejected(self) -> None:
        output_text = json.dumps({"answer_markdown": "x", "cited_chunk_ids": [], "extra": "y"})
        adapter, client = _make_adapter([SimpleNamespace(output_text=output_text, id="r1")])
        with pytest.raises(TutorModelProviderError):
            await adapter.generate(_request())
        assert len(client.responses.calls) == 1

    async def test_oversized_cited_chunk_ids_is_rejected(self) -> None:
        candidate = _candidate()
        adapter, client = _make_adapter([_response(cited_ids=[str(candidate.chunk.chunk_id)] * 51)])
        with pytest.raises(TutorModelProviderError):
            await adapter.generate(_request(candidates=[candidate]))
        assert len(client.responses.calls) == 1


class TestProviderFailures:
    async def test_timeout_raises_provider_error(self) -> None:
        exc = APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
        adapter, client = _make_adapter([exc])
        with pytest.raises(TutorModelProviderError):
            await adapter.generate(_request())
        assert len(client.responses.calls) == 1

    async def test_api_error_raises_provider_error(self) -> None:
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        exc = APIError(message="boom", request=request, body=None)
        adapter, client = _make_adapter([exc])
        with pytest.raises(TutorModelProviderError):
            await adapter.generate(_request())
        assert len(client.responses.calls) == 1


class TestSecretHygiene:
    async def test_api_key_never_appears_in_exception_text(self) -> None:
        adapter, _ = _make_adapter([SimpleNamespace(output_text="not json", id="r1")])
        with pytest.raises(TutorModelProviderError) as exc_info:
            await adapter.generate(_request())
        assert _FAKE_API_KEY not in str(exc_info.value)


class TestClientLifecycle:
    async def test_aclose_does_not_close_an_injected_client(self) -> None:
        adapter, client = _make_adapter([_response()])
        await adapter.aclose()
        # A fake injected client has no `close()` - if `aclose()` tried to
        # close it, this would raise AttributeError.
        assert client is adapter._client  # noqa: SLF001 - test-only introspection
