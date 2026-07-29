"""Unit tests for `OllamaResearchSynthesisAdapter` (spec G2D2/H1
correction pass, section 6).

Every request goes through an injected `httpx.AsyncClient` built on
`httpx.MockTransport` - no real network access and no live call to
Ollama Cloud is ever made in this file.
"""

from __future__ import annotations

import json
from uuid import uuid4

import httpx

from stock_research_core.application.exceptions import ResearchModelProviderError
from stock_research_core.application.live_research.synthesis_models import (
    ResearchEvidenceInput,
    ResearchSynthesisRequest,
)
from stock_research_core.domain.live_research.enums import ResearchScope
from stock_research_core.infrastructure.live_research.ollama_research_synthesis import (
    DEFAULT_OLLAMA_CLOUD_BASE_URL,
    OllamaResearchSynthesisAdapter,
)

_FAKE_API_KEY = "sk-test-only-not-a-real-secret-abc123"


def _request(evidence_ids: list | None = None) -> ResearchSynthesisRequest:
    ids = evidence_ids if evidence_ids is not None else [uuid4()]
    return ResearchSynthesisRequest(
        system_instructions="You are FinQuest's research assistant.",
        user_question="What happened to Nvidia this week?",
        scope=ResearchScope.NEWS_SCAN,
        evidence_items=[
            ResearchEvidenceInput(
                evidence_id=evidence_id, source_title="Nvidia earnings report", publisher="Example Wire",
                excerpt="Nvidia reported strong quarterly results.", official=False,
            )
            for evidence_id in ids
        ],
        prompt_version="v1",
    )


def _ollama_response(*, answer="Nvidia reported strong earnings. [1]", cited_ids=None) -> httpx.Response:
    body = {
        "model": "gpt-oss:20b", "created_at": "2026-01-01T00:00:00Z",
        "message": {"role": "assistant", "content": json.dumps({"answer_markdown": answer, "cited_evidence_ids": cited_ids or []})},
        "done": True,
    }
    return httpx.Response(200, json=body)


def _client_for(responses: list) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
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


def _make_adapter(client: httpx.AsyncClient, **overrides) -> OllamaResearchSynthesisAdapter:
    kwargs = {"api_key": _FAKE_API_KEY, "model_name": "gpt-oss:20b", "client": client}
    kwargs.update(overrides)
    return OllamaResearchSynthesisAdapter(**kwargs)


async def test_valid_ollama_research_synthesis_returns_the_answer_and_cited_ids() -> None:
    request = _request()
    evidence_id = request.evidence_items[0].evidence_id
    client, captured = _client_for([_ollama_response(cited_ids=[str(evidence_id)])])
    adapter = _make_adapter(client)

    result = await adapter.generate(request)

    assert result.answer_markdown == "Nvidia reported strong earnings. [1]"
    assert result.cited_evidence_ids == [evidence_id]
    assert str(captured[0].url) == f"{DEFAULT_OLLAMA_CLOUD_BASE_URL}/chat"
    assert captured[0].headers["authorization"] == f"Bearer {_FAKE_API_KEY}"


async def test_malformed_response_retries_once_then_succeeds() -> None:
    request = _request()
    evidence_id = request.evidence_items[0].evidence_id
    malformed = httpx.Response(200, json={"model": "gpt-oss:20b", "message": {"role": "assistant", "content": "not json"}})
    client, captured = _client_for([malformed, _ollama_response(cited_ids=[str(evidence_id)])])
    adapter = _make_adapter(client)

    result = await adapter.generate(request)

    assert result.cited_evidence_ids == [evidence_id]
    assert len(captured) == 2


async def test_malformed_response_twice_raises_provider_error() -> None:
    malformed = httpx.Response(200, json={"model": "gpt-oss:20b", "message": {"role": "assistant", "content": "not json"}})
    client, _captured = _client_for([malformed, malformed])
    adapter = _make_adapter(client)

    try:
        await adapter.generate(_request())
        raise AssertionError("expected ResearchModelProviderError")
    except ResearchModelProviderError:
        pass


async def test_non_2xx_response_raises_provider_error() -> None:
    client, _captured = _client_for([httpx.Response(500, json={"error": "boom"})] * 3)
    adapter = _make_adapter(client)

    try:
        await adapter.generate(_request())
        raise AssertionError("expected ResearchModelProviderError")
    except ResearchModelProviderError:
        pass
