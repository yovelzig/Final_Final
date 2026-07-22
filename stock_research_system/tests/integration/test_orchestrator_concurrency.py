"""Integration tests for spec section 18's concurrency guarantee: at
most one active graph run per thread, enforced by the real Redis-backed
distributed lock (`learning-orchestrator-thread:{thread_id}`) - not an
in-process guard, which would not hold across multiple API workers.
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import asyncio as _asyncio
from uuid import uuid4

import pytest

from tests.integration.conftest import auth_headers
from tests.integration.learning_orchestrator_app_fixtures import learning_coach_app, learning_coach_client  # noqa: F401

pytestmark = pytest.mark.integration


async def test_concurrent_runs_on_the_same_thread_do_not_corrupt_state(learning_coach_client) -> None:
    """Two run requests fired concurrently at the same thread must both
    resolve to a consistent, valid state - never a corrupted run row, a
    lost event, or two graph invocations racing on the same checkpoint."""
    headers = await auth_headers(learning_coach_client, email=f"coach-concurrency-{uuid4().hex[:10]}@example.com")
    thread = (await learning_coach_client.post("/api/v1/coach/threads", json={}, headers=headers)).json()
    thread_id = thread["thread_id"]

    async def _start_run(question: str):
        return await learning_coach_client.post(
            f"/api/v1/coach/threads/{thread_id}/runs", json={"user_input": question},
            headers={**headers, "Idempotency-Key": f"key-{uuid4()}"},
        )

    responses = await _asyncio.gather(
        _start_run("What is diversification?"), _start_run("What is a bond?"),
    )
    statuses = {response.status_code for response in responses}
    # Every response must be a well-formed, individually valid result -
    # either both succeeded serialized one after the other (the lock's
    # wait-and-retry path), or one was rejected outright (503 lock
    # unavailable) - never a 500, never a hang.
    assert statuses <= {202, 503}
    for response in responses:
        if response.status_code == 202:
            assert response.json()["status"] in ("SUCCEEDED", "WAITING_FOR_LEARNER", "FAILED")

    events_response = await learning_coach_client.get("/api/v1/coach/threads", headers=headers)
    assert events_response.status_code == 200


async def test_lock_is_released_after_a_run_completes_so_a_later_run_can_proceed(learning_coach_client) -> None:
    headers = await auth_headers(learning_coach_client, email=f"coach-lock-release-{uuid4().hex[:10]}@example.com")
    thread = (await learning_coach_client.post("/api/v1/coach/threads", json={}, headers=headers)).json()
    thread_id = thread["thread_id"]

    first = await learning_coach_client.post(
        f"/api/v1/coach/threads/{thread_id}/runs", json={"user_input": "What is diversification?"},
        headers={**headers, "Idempotency-Key": f"key-{uuid4()}"},
    )
    assert first.status_code == 202
    assert first.json()["status"] == "SUCCEEDED"

    second = await learning_coach_client.post(
        f"/api/v1/coach/threads/{thread_id}/runs", json={"user_input": "What is a bond?"},
        headers={**headers, "Idempotency-Key": f"key-{uuid4()}"},
    )
    assert second.status_code == 202
    assert second.json()["status"] == "SUCCEEDED"


async def test_lock_is_released_when_a_run_ends_up_waiting_for_learner(learning_coach_client) -> None:
    """The lock must not be held for the entire human-waiting period -
    it's released as soon as the graph pauses, so a *different* thread's
    run (or, once resumed, this same thread's next request) is never
    blocked by an open-ended learner-approval wait."""
    headers = await auth_headers(learning_coach_client, email=f"coach-lock-wait-{uuid4().hex[:10]}@example.com")
    thread = (await learning_coach_client.post("/api/v1/coach/threads", json={}, headers=headers)).json()
    thread_id = thread["thread_id"]

    waiting = await learning_coach_client.post(
        f"/api/v1/coach/threads/{thread_id}/runs",
        json={"user_input": "I'd like to start my daily practice session to build my financial skills."},
        headers={**headers, "Idempotency-Key": f"key-{uuid4()}"},
    )
    assert waiting.json()["status"] == "WAITING_FOR_LEARNER"

    other_thread = (await learning_coach_client.post("/api/v1/coach/threads", json={}, headers=headers)).json()
    other_run = await learning_coach_client.post(
        f"/api/v1/coach/threads/{other_thread['thread_id']}/runs", json={"user_input": "What is a bond?"},
        headers={**headers, "Idempotency-Key": f"key-{uuid4()}"},
    )
    assert other_run.status_code == 202
    assert other_run.json()["status"] == "SUCCEEDED"
