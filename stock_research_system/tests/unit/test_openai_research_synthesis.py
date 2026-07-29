"""Unit tests for `OpenAIResearchSynthesisAdapter` (spec G2D2/H1
correction pass, section 6).

Every request goes through an injected fake client exposing
`.responses.create(...)` - no real network access and no live call to
OpenAI is ever made in this file.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
from openai import APITimeoutError

from stock_research_core.application.exceptions import ResearchModelProviderError
from stock_research_core.application.live_research.synthesis_models import (
    ResearchEvidenceInput,
    ResearchSynthesisRequest,
)
from stock_research_core.domain.live_research.enums import ResearchScope
from stock_research_core.infrastructure.live_research.openai_research_synthesis import (
    OpenAIResearchSynthesisAdapter,
)

_FAKE_API_KEY = "sk-test-only-not-a-real-secret-abc123"


def _request(evidence_ids: list | None = None) -> ResearchSynthesisRequest:
    ids = evidence_ids if evidence_ids is not None else [uuid4()]
    return ResearchSynthesisRequest(
        system_instructions="You are FinQuest's research assistant.",
        user_question="What happened to Nvidia this week?", scope=ResearchScope.NEWS_SCAN,
        evidence_items=[
            ResearchEvidenceInput(
                evidence_id=evidence_id, source_title="Nvidia earnings report", publisher="Example Wire",
                excerpt="Nvidia reported strong quarterly results.", official=False,
            )
            for evidence_id in ids
        ],
        prompt_version="v1",
    )


def _response(*, answer="Nvidia reported strong earnings.", cited_ids=None, response_id="resp_1"):
    output_text = json.dumps({"answer_markdown": answer, "cited_evidence_ids": cited_ids or []})
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


def _make_adapter(results: list, **overrides) -> tuple[OpenAIResearchSynthesisAdapter, _FakeClient]:
    client = _FakeClient(results)
    kwargs = {"api_key": _FAKE_API_KEY, "model_name": "gpt-5-reasoning", "client": client}
    kwargs.update(overrides)
    return OpenAIResearchSynthesisAdapter(**kwargs), client


async def test_valid_openai_research_synthesis_returns_the_answer_and_cited_ids() -> None:
    request = _request()
    evidence_id = request.evidence_items[0].evidence_id
    adapter, client = _make_adapter([_response(cited_ids=[str(evidence_id)])])

    result = await adapter.generate(request)

    assert result.answer_markdown == "Nvidia reported strong earnings."
    assert result.cited_evidence_ids == [evidence_id]
    assert client.responses.calls[0]["tools"] == []


async def test_timeout_raises_research_model_provider_error() -> None:
    adapter, _client = _make_adapter([APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))])

    try:
        await adapter.generate(_request())
        raise AssertionError("expected ResearchModelProviderError")
    except ResearchModelProviderError:
        pass


async def test_malformed_response_raises_research_model_provider_error_without_a_retry() -> None:
    adapter, client = _make_adapter([SimpleNamespace(output_text="not json", id="resp_1")])

    try:
        await adapter.generate(_request())
        raise AssertionError("expected ResearchModelProviderError")
    except ResearchModelProviderError:
        pass
    assert len(client.responses.calls) == 1
