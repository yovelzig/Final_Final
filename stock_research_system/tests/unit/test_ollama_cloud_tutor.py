"""Unit tests for `OllamaCloudTutorAdapter` (Phase D).

Every request goes through an injected `httpx.AsyncClient` built on
`httpx.MockTransport` - no real network access and no live call to Ollama
Cloud is ever made in this file.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest

from stock_research_core.application.ai_tutor.models import RetrievalCandidate, TutorModelRequest
from stock_research_core.application.exceptions import TutorModelProviderError
from stock_research_core.domain.ai_tutor.enums import (
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeSourceType,
    TutorProviderType,
)
from stock_research_core.domain.ai_tutor.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from stock_research_core.infrastructure.ai_tutor.ollama_cloud_tutor import (
    DEFAULT_OLLAMA_CLOUD_BASE_URL,
    OllamaCloudTutorAdapter,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_HASH = hashlib.sha256(b"x").hexdigest()
_FAKE_API_KEY = "sk-test-only-not-a-real-secret-abc123"


def _candidate(content: str = "Compound interest grows a period's balance.") -> RetrievalCandidate:
    source = KnowledgeSource(
        source_type=KnowledgeSourceType.LOCAL_MARKDOWN,
        title="Approved Source",
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
        user_question=question,
        conversation_messages=[],
        retrieved_candidates=candidates or [],
        prompt_version="v1",
    )


def _ollama_message(
    *, answer: str = "Here is the answer. [1]", cited_ids: list[str] | None = None, thinking: str | None = None
) -> dict:
    message: dict = {
        "role": "assistant",
        "content": json.dumps({"answer_markdown": answer, "cited_chunk_ids": cited_ids or []}),
    }
    if thinking is not None:
        message["thinking"] = thinking
    return message


def _ollama_response(**kwargs) -> httpx.Response:
    body = {
        "model": "gpt-oss:20b",
        "created_at": "2026-01-01T00:00:00Z",
        "message": _ollama_message(**kwargs),
        "done": True,
    }
    return httpx.Response(200, json=body)


def _client_for(responses: list) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    """Builds a mock-transport client returning `responses` in sequence.

    Each item is either an `httpx.Response` or an `Exception` instance to raise.
    """
    captured: list[httpx.Request] = []
    state = {"index": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        index = state["index"]
        state["index"] += 1
        result = responses[index]
        if isinstance(result, Exception):
            raise result
        return result

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client, captured


def _make_adapter(client: httpx.AsyncClient, **overrides) -> OllamaCloudTutorAdapter:
    kwargs = {
        "api_key": _FAKE_API_KEY,
        "model_name": "gpt-oss:20b",
        "client": client,
    }
    kwargs.update(overrides)
    return OllamaCloudTutorAdapter(**kwargs)


class TestRequestShape:
    async def test_correct_endpoint(self) -> None:
        client, captured = _client_for([_ollama_response()])
        adapter = _make_adapter(client)

        await adapter.generate(_request())

        assert str(captured[0].url) == f"{DEFAULT_OLLAMA_CLOUD_BASE_URL}/chat"
        assert str(captured[0].url) == "https://ollama.com/api/chat"

    async def test_correct_bearer_authorization_header(self) -> None:
        client, captured = _client_for([_ollama_response()])
        adapter = _make_adapter(client)

        await adapter.generate(_request())

        assert captured[0].headers["authorization"] == f"Bearer {_FAKE_API_KEY}"

    async def test_request_body_fields(self) -> None:
        client, captured = _client_for([_ollama_response()])
        adapter = _make_adapter(client, thinking_level="low")

        await adapter.generate(_request())

        payload = json.loads(captured[0].content)
        assert payload["model"] == "gpt-oss:20b"
        assert isinstance(payload["messages"], list) and len(payload["messages"]) >= 2
        assert payload["stream"] is False
        assert payload["think"] == "low"
        assert payload["options"]["temperature"] == 0
        assert "num_predict" in payload["options"]
        assert "format" not in payload

    async def test_base_url_rstrips_trailing_slash(self) -> None:
        client, captured = _client_for([_ollama_response()])
        adapter = _make_adapter(client, base_url="https://ollama.com/api/")

        await adapter.generate(_request())

        assert str(captured[0].url) == "https://ollama.com/api/chat"


class TestSuccessfulResponses:
    async def test_strict_json_response_parsed(self) -> None:
        client, _ = _client_for([_ollama_response(answer="The answer.")])
        adapter = _make_adapter(client)

        result = await adapter.generate(_request())

        assert result.answer_markdown == "The answer."
        assert result.provider_type == TutorProviderType.OLLAMA_CLOUD
        assert result.model_name == "gpt-oss:20b"

    async def test_valid_citations_converted_to_uuids(self) -> None:
        candidate = _candidate()
        chunk_id = str(candidate.chunk.chunk_id)
        client, _ = _client_for([_ollama_response(cited_ids=[chunk_id])])
        adapter = _make_adapter(client)

        result = await adapter.generate(_request(candidates=[candidate]))

        assert result.cited_chunk_ids == [candidate.chunk.chunk_id]
        assert isinstance(result.cited_chunk_ids[0], UUID)

    async def test_duplicate_valid_citations_deduplicated_preserving_order(self) -> None:
        candidate_a = _candidate("First fact.")
        candidate_b = _candidate("Second fact.")
        ids = [str(candidate_a.chunk.chunk_id), str(candidate_b.chunk.chunk_id), str(candidate_a.chunk.chunk_id)]
        client, _ = _client_for([_ollama_response(cited_ids=ids)])
        adapter = _make_adapter(client)

        result = await adapter.generate(_request(candidates=[candidate_a, candidate_b]))

        assert result.cited_chunk_ids == [candidate_a.chunk.chunk_id, candidate_b.chunk.chunk_id]

    async def test_message_thinking_is_ignored_and_not_returned(self) -> None:
        client, _ = _client_for([_ollama_response(answer="Answer.", thinking="secret chain-of-thought reasoning")])
        adapter = _make_adapter(client)

        result = await adapter.generate(_request())

        assert result.answer_markdown == "Answer."
        assert "thinking" not in result.model_dump()
        assert "secret chain-of-thought reasoning" not in result.model_dump_json()

    async def test_unicode_survives_unchanged(self) -> None:
        answer = "A period’s balance grows: ריבית דריבית."
        client, _ = _client_for([_ollama_response(answer=answer)])
        adapter = _make_adapter(client)

        result = await adapter.generate(_request())

        assert result.answer_markdown == answer


class TestCorrectionRetry:
    async def test_invalid_json_triggers_exactly_one_correction_attempt(self) -> None:
        bad = httpx.Response(200, json={"model": "gpt-oss:20b", "message": {"role": "assistant", "content": "not json"}})
        good = _ollama_response(answer="Fixed answer.")
        client, captured = _client_for([bad, good])
        adapter = _make_adapter(client)

        result = await adapter.generate(_request())

        assert result.answer_markdown == "Fixed answer."
        assert len(captured) == 2

    async def test_unknown_citation_triggers_exactly_one_correction_attempt(self) -> None:
        candidate = _candidate()
        bad = _ollama_response(cited_ids=[str(uuid4())])  # not in retrieved_candidates
        good = _ollama_response(answer="Fixed answer.", cited_ids=[str(candidate.chunk.chunk_id)])
        client, captured = _client_for([bad, good])
        adapter = _make_adapter(client)

        result = await adapter.generate(_request(candidates=[candidate]))

        assert result.answer_markdown == "Fixed answer."
        assert result.cited_chunk_ids == [candidate.chunk.chunk_id]
        assert len(captured) == 2

    async def test_second_invalid_response_raises_provider_error(self) -> None:
        bad = httpx.Response(200, json={"model": "gpt-oss:20b", "message": {"role": "assistant", "content": "still not json"}})
        client, captured = _client_for([bad, bad])
        adapter = _make_adapter(client)

        with pytest.raises(TutorModelProviderError):
            await adapter.generate(_request())

        assert len(captured) == 2

    async def test_invalid_uuid_in_citations_is_rejected(self) -> None:
        candidate = _candidate()
        bad = _ollama_response(cited_ids=["not-a-uuid"])
        client, captured = _client_for([bad, bad])
        adapter = _make_adapter(client)

        with pytest.raises(TutorModelProviderError):
            await adapter.generate(_request(candidates=[candidate]))
        assert len(captured) == 2

    async def test_non_list_cited_chunk_ids_is_rejected(self) -> None:
        body = {
            "model": "gpt-oss:20b",
            "message": {"role": "assistant", "content": json.dumps({"answer_markdown": "x", "cited_chunk_ids": "not-a-list"})},
        }
        bad = httpx.Response(200, json=body)
        client, captured = _client_for([bad, bad])
        adapter = _make_adapter(client)

        with pytest.raises(TutorModelProviderError):
            await adapter.generate(_request())
        assert len(captured) == 2

    async def test_empty_answer_markdown_is_rejected(self) -> None:
        bad = _ollama_response(answer="   ")
        client, captured = _client_for([bad, bad])
        adapter = _make_adapter(client)

        with pytest.raises(TutorModelProviderError):
            await adapter.generate(_request())
        assert len(captured) == 2

    async def test_extra_top_level_key_is_rejected(self) -> None:
        body = {
            "model": "gpt-oss:20b",
            "message": {
                "role": "assistant",
                "content": json.dumps(
                    {"answer_markdown": "x", "cited_chunk_ids": [], "extra_field": "unexpected"}
                ),
            },
        }
        bad = httpx.Response(200, json=body)
        client, captured = _client_for([bad, bad])
        adapter = _make_adapter(client)

        with pytest.raises(TutorModelProviderError):
            await adapter.generate(_request())
        assert len(captured) == 2

    async def test_oversized_cited_chunk_ids_list_is_rejected(self) -> None:
        candidate = _candidate()
        oversized_ids = [str(candidate.chunk.chunk_id)] * 51
        bad = _ollama_response(cited_ids=oversized_ids)
        client, captured = _client_for([bad, bad])
        adapter = _make_adapter(client)

        with pytest.raises(TutorModelProviderError):
            await adapter.generate(_request(candidates=[candidate]))
        assert len(captured) == 2

    async def test_oversized_answer_markdown_is_rejected(self) -> None:
        bad = _ollama_response(answer="x" * 20_001)
        client, captured = _client_for([bad, bad])
        adapter = _make_adapter(client)

        with pytest.raises(TutorModelProviderError):
            await adapter.generate(_request())
        assert len(captured) == 2

    async def test_citations_are_never_inferred_from_prose(self) -> None:
        """A UUID-looking string embedded in the free-text answer must
        never become a citation - only the structured `cited_chunk_ids`
        field is ever read for citations."""
        candidate = _candidate()
        prose_with_uuid = f"See chunk {candidate.chunk.chunk_id} for details."
        client, _ = _client_for([_ollama_response(answer=prose_with_uuid, cited_ids=[])])
        adapter = _make_adapter(client)

        result = await adapter.generate(_request(candidates=[candidate]))

        assert result.cited_chunk_ids == []


class TestTransportRetries:
    async def test_timeout_retries_are_bounded_then_raise(self) -> None:
        exc = httpx.TimeoutException("timed out")
        client, captured = _client_for([exc, exc, exc])
        adapter = _make_adapter(client)

        with pytest.raises(TutorModelProviderError):
            await adapter.generate(_request())

        assert len(captured) == 3  # 1 initial attempt + 2 bounded retries

    async def test_transient_5xx_retries_then_succeeds_within_bound(self) -> None:
        client, captured = _client_for([httpx.Response(503), httpx.Response(502), _ollama_response(answer="ok")])
        adapter = _make_adapter(client)

        result = await adapter.generate(_request())

        assert result.answer_markdown == "ok"
        assert len(captured) == 3

    async def test_429_retries_are_bounded_then_raise(self) -> None:
        client, captured = _client_for([httpx.Response(429), httpx.Response(429), httpx.Response(429)])
        adapter = _make_adapter(client)

        with pytest.raises(TutorModelProviderError):
            await adapter.generate(_request())

        assert len(captured) == 3

    async def test_non_retryable_4xx_fails_without_retrying(self) -> None:
        client, captured = _client_for([httpx.Response(401)])
        adapter = _make_adapter(client)

        with pytest.raises(TutorModelProviderError):
            await adapter.generate(_request())

        assert len(captured) == 1


class TestSecretHygiene:
    async def test_api_key_never_appears_in_exception_text(self) -> None:
        client, _ = _client_for([httpx.Response(401)])
        adapter = _make_adapter(client)

        with pytest.raises(TutorModelProviderError) as exc_info:
            await adapter.generate(_request())

        assert _FAKE_API_KEY not in str(exc_info.value)

    async def test_api_key_never_appears_in_exception_text_after_exhausted_retries(self) -> None:
        client, _ = _client_for([httpx.Response(500), httpx.Response(500), httpx.Response(500)])
        adapter = _make_adapter(client)

        with pytest.raises(TutorModelProviderError) as exc_info:
            await adapter.generate(_request())

        assert _FAKE_API_KEY not in str(exc_info.value)


class TestClientLifecycle:
    async def test_aclose_closes_only_an_owned_client(self) -> None:
        adapter = OllamaCloudTutorAdapter(api_key=_FAKE_API_KEY, model_name="gpt-oss:20b")
        owned_client = adapter._client  # noqa: SLF001 - test-only introspection

        await adapter.aclose()

        assert owned_client.is_closed

    async def test_aclose_does_not_close_an_injected_client(self) -> None:
        client, _ = _client_for([_ollama_response()])
        adapter = _make_adapter(client)

        await adapter.aclose()

        assert not client.is_closed
        await client.aclose()
