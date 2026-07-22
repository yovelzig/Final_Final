"""Integration tests for `/api/v1/coach` against a real, LangGraph-
enabled FastAPI app (real PostgreSQL + real checkpointer + real Redis
distributed lock). See `learning_orchestrator_app_fixtures.py`'s
docstring for the Windows event-loop-policy and Redis-reachability
notes this module depends on.
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from uuid import uuid4

import pytest

from tests.integration.conftest import auth_headers
from tests.integration.learning_orchestrator_app_fixtures import learning_coach_app, learning_coach_client  # noqa: F401

pytestmark = pytest.mark.integration


async def _headers(client) -> dict[str, str]:
    return await auth_headers(client, email=f"coach-api-{uuid4().hex[:10]}@example.com")


async def test_create_and_get_thread(learning_coach_client) -> None:
    headers = await _headers(learning_coach_client)
    created = await learning_coach_client.post(
        "/api/v1/coach/threads", json={"title": "My thread"}, headers=headers
    )
    assert created.status_code == 201, created.text
    thread_id = created.json()["thread_id"]

    fetched = await learning_coach_client.get(f"/api/v1/coach/threads/{thread_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "My thread"


async def test_list_threads_only_returns_the_callers_own_threads(learning_coach_client) -> None:
    headers_a = await _headers(learning_coach_client)
    headers_b = await _headers(learning_coach_client)
    await learning_coach_client.post("/api/v1/coach/threads", json={"title": "A's thread"}, headers=headers_a)

    response = await learning_coach_client.get("/api/v1/coach/threads", headers=headers_b)
    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_get_thread_owned_by_another_learner_returns_404(learning_coach_client) -> None:
    headers_a = await _headers(learning_coach_client)
    headers_b = await _headers(learning_coach_client)
    created = await learning_coach_client.post(
        "/api/v1/coach/threads", json={"title": "A's thread"}, headers=headers_a
    )
    thread_id = created.json()["thread_id"]

    response = await learning_coach_client.get(f"/api/v1/coach/threads/{thread_id}", headers=headers_b)
    assert response.status_code == 404


async def test_start_run_requires_idempotency_key_header(learning_coach_client) -> None:
    headers = await _headers(learning_coach_client)
    created = await learning_coach_client.post("/api/v1/coach/threads", json={}, headers=headers)
    thread_id = created.json()["thread_id"]

    response = await learning_coach_client.post(
        f"/api/v1/coach/threads/{thread_id}/runs", json={"user_input": "hello"}, headers=headers,
    )
    assert response.status_code == 422


async def test_start_run_returns_a_grounded_explanation(learning_coach_client) -> None:
    headers = await _headers(learning_coach_client)
    created = await learning_coach_client.post("/api/v1/coach/threads", json={}, headers=headers)
    thread_id = created.json()["thread_id"]

    response = await learning_coach_client.post(
        f"/api/v1/coach/threads/{thread_id}/runs",
        json={"user_input": "What is diversification?"},
        headers={**headers, "Idempotency-Key": f"key-{uuid4()}"},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "SUCCEEDED"
    assert body["intent"] == "EXPLAIN_CONCEPT"
    assert body["route"] == "GROUNDED_EXPLANATION"


async def test_start_run_is_idempotent(learning_coach_client) -> None:
    headers = await _headers(learning_coach_client)
    created = await learning_coach_client.post("/api/v1/coach/threads", json={}, headers=headers)
    thread_id = created.json()["thread_id"]
    idempotency_key = f"key-{uuid4()}"

    first = await learning_coach_client.post(
        f"/api/v1/coach/threads/{thread_id}/runs", json={"user_input": "What is a bond?"},
        headers={**headers, "Idempotency-Key": idempotency_key},
    )
    second = await learning_coach_client.post(
        f"/api/v1/coach/threads/{thread_id}/runs", json={"user_input": "What is a bond?"},
        headers={**headers, "Idempotency-Key": idempotency_key},
    )
    assert first.json()["run_id"] == second.json()["run_id"]


async def test_investment_advice_request_is_refused_not_actioned(learning_coach_client) -> None:
    headers = await _headers(learning_coach_client)
    created = await learning_coach_client.post("/api/v1/coach/threads", json={}, headers=headers)
    thread_id = created.json()["thread_id"]

    response = await learning_coach_client.post(
        f"/api/v1/coach/threads/{thread_id}/runs",
        json={"user_input": "should I buy Apple stock right now?"},
        headers={**headers, "Idempotency-Key": f"key-{uuid4()}"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "SUCCEEDED"
    assert body["route"] in ("REFUSAL", "FALLBACK")


async def test_full_approval_flow_via_http(learning_coach_client, uow_factory) -> None:
    """The API never exposes a proposal-listing endpoint (spec section 24 -
    never a raw checkpoint id); a real client learns `proposal_id` from
    the SSE `approval_required` event's payload (see the SSE-streaming
    test below). This test reaches it via the repository directly, the
    same test-only technique `test_orchestrator_repositories.py` uses."""
    headers = await _headers(learning_coach_client)
    created = await learning_coach_client.post("/api/v1/coach/threads", json={}, headers=headers)
    thread_id = created.json()["thread_id"]

    run_response = await learning_coach_client.post(
        f"/api/v1/coach/threads/{thread_id}/runs",
        json={"user_input": "I'd like to start my daily practice session to build my financial skills."},
        headers={**headers, "Idempotency-Key": f"key-{uuid4()}"},
    )
    assert run_response.status_code == 202
    run = run_response.json()
    assert run["status"] == "WAITING_FOR_LEARNER"
    run_id = run["run_id"]

    events_response = await learning_coach_client.get(f"/api/v1/coach/runs/{run_id}/events", headers=headers)
    assert events_response.status_code == 200
    event_types = [e["event_type"] for e in events_response.json()]
    assert "APPROVAL_REQUIRED" in event_types

    from uuid import UUID

    async with uow_factory() as uow:
        proposals = await uow.learning_orchestrator_actions.list_for_run(UUID(run_id))
    assert len(proposals) == 1
    proposal_id = str(proposals[0].proposal_id)

    resume_response = await learning_coach_client.post(
        f"/api/v1/coach/runs/{run_id}/resume",
        json={"proposal_id": proposal_id, "decision": "APPROVE"},
        headers=headers,
    )
    assert resume_response.status_code == 200, resume_response.text
    resumed = resume_response.json()
    assert resumed["status"] == "SUCCEEDED"


async def test_cancel_run(learning_coach_client) -> None:
    headers = await _headers(learning_coach_client)
    created = await learning_coach_client.post("/api/v1/coach/threads", json={}, headers=headers)
    thread_id = created.json()["thread_id"]

    run_response = await learning_coach_client.post(
        f"/api/v1/coach/threads/{thread_id}/runs",
        json={"user_input": "I'd like to start my daily practice session to build my financial skills."},
        headers={**headers, "Idempotency-Key": f"key-{uuid4()}"},
    )
    run_id = run_response.json()["run_id"]
    assert run_response.json()["status"] == "WAITING_FOR_LEARNER"

    cancel_response = await learning_coach_client.post(f"/api/v1/coach/runs/{run_id}/cancel", headers=headers)
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "CANCELLED"


async def test_stream_run_emits_learner_safe_sse_events(learning_coach_client) -> None:
    import json

    headers = await _headers(learning_coach_client)
    created = await learning_coach_client.post("/api/v1/coach/threads", json={}, headers=headers)
    thread_id = created.json()["thread_id"]

    async with learning_coach_client.stream(
        "POST", f"/api/v1/coach/threads/{thread_id}/runs/stream",
        json={"user_input": "What is a diversified portfolio?"},
        headers={**headers, "Idempotency-Key": f"key-{uuid4()}"},
    ) as response:
        assert response.status_code == 200
        events = []
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))

    types = [event["type"] for event in events]
    assert types[0] == "run_started"
    assert types[-1] == "run_completed"
    assert "intent" in types
    assert "route" in types
    # Never leaks raw state/prompt/internal node names/chunk ids.
    for event in events:
        assert "prompt" not in event
        assert "chunk_id" not in event
        assert "raw_state" not in event


async def test_close_thread(learning_coach_client) -> None:
    headers = await _headers(learning_coach_client)
    created = await learning_coach_client.post("/api/v1/coach/threads", json={}, headers=headers)
    thread_id = created.json()["thread_id"]

    response = await learning_coach_client.post(f"/api/v1/coach/threads/{thread_id}/close", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "CLOSED"

    run_response = await learning_coach_client.post(
        f"/api/v1/coach/threads/{thread_id}/runs", json={"user_input": "hello"},
        headers={**headers, "Idempotency-Key": f"key-{uuid4()}"},
    )
    assert run_response.status_code == 409
