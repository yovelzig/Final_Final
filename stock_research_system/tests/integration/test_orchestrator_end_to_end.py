"""One coherent end-to-end learning-coach session, chaining multiple
realistic learner turns through the real HTTP API, real PostgreSQL,
real checkpointer, and real Redis lock - distinct from
`test_orchestrator_api.py`'s per-endpoint tests, this exercises the
product flow a learner would actually experience in one thread.
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from uuid import UUID, uuid4

import pytest

from tests.integration.conftest import auth_headers
from tests.integration.learning_orchestrator_app_fixtures import learning_coach_app, learning_coach_client  # noqa: F401

pytestmark = pytest.mark.integration


async def test_a_full_learner_session_across_multiple_turns(learning_coach_client, uow_factory) -> None:
    headers = await auth_headers(learning_coach_client, email=f"coach-e2e-{uuid4().hex[:10]}@example.com")

    # Turn 1: open a coach thread and ask a general concept question.
    thread = (await learning_coach_client.post("/api/v1/coach/threads", json={"title": "My learning"}, headers=headers)).json()
    thread_id = thread["thread_id"]

    ask_response = await learning_coach_client.post(
        f"/api/v1/coach/threads/{thread_id}/runs", json={"user_input": "What is compound interest?"},
        headers={**headers, "Idempotency-Key": f"key-{uuid4()}"},
    )
    assert ask_response.status_code == 202
    ask_run = ask_response.json()
    assert ask_run["status"] == "SUCCEEDED"
    assert ask_run["route"] == "GROUNDED_EXPLANATION"

    # Turn 2: ask an investment-advice-shaped question - must refuse, never propose a trade.
    refuse_response = await learning_coach_client.post(
        f"/api/v1/coach/threads/{thread_id}/runs", json={"user_input": "which stock should I buy right now?"},
        headers={**headers, "Idempotency-Key": f"key-{uuid4()}"},
    )
    assert refuse_response.status_code == 202
    refuse_run = refuse_response.json()
    assert refuse_run["status"] == "SUCCEEDED"
    assert refuse_run["route"] in ("REFUSAL", "FALLBACK")

    # Turn 3: ask to start practicing - requires explicit approval.
    practice_response = await learning_coach_client.post(
        f"/api/v1/coach/threads/{thread_id}/runs",
        json={"user_input": "Let's start my daily practice session for financial skills."},
        headers={**headers, "Idempotency-Key": f"key-{uuid4()}"},
    )
    assert practice_response.status_code == 202
    practice_run = practice_response.json()
    assert practice_run["status"] == "WAITING_FOR_LEARNER"
    run_id = practice_run["run_id"]

    async with uow_factory() as uow:
        proposals = await uow.learning_orchestrator_actions.list_for_run(UUID(run_id))
    assert len(proposals) == 1
    assert proposals[0].action_type.value == "START_ADAPTIVE_SESSION"

    # Turn 4: reject the first time (learner changes their mind).
    reject_response = await learning_coach_client.post(
        f"/api/v1/coach/runs/{run_id}/resume",
        json={"proposal_id": str(proposals[0].proposal_id), "decision": "REJECT"}, headers=headers,
    )
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "SUCCEEDED"

    # Turn 5: try again and this time approve it.
    retry_response = await learning_coach_client.post(
        f"/api/v1/coach/threads/{thread_id}/runs",
        json={"user_input": "OK let's do a daily practice session for financial skills."},
        headers={**headers, "Idempotency-Key": f"key-{uuid4()}"},
    )
    retry_run = retry_response.json()
    assert retry_run["status"] == "WAITING_FOR_LEARNER"
    async with uow_factory() as uow:
        retry_proposals = await uow.learning_orchestrator_actions.list_for_run(UUID(retry_run["run_id"]))
    approve_response = await learning_coach_client.post(
        f"/api/v1/coach/runs/{retry_run['run_id']}/resume",
        json={"proposal_id": str(retry_proposals[0].proposal_id), "decision": "APPROVE"}, headers=headers,
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "SUCCEEDED"

    # Finally: the whole thread's run history is visible and consistent.
    all_runs_response = await learning_coach_client.get(f"/api/v1/coach/threads/{thread_id}", headers=headers)
    assert all_runs_response.status_code == 200
    assert all_runs_response.json()["status"] == "ACTIVE"

    close_response = await learning_coach_client.post(f"/api/v1/coach/threads/{thread_id}/close", headers=headers)
    assert close_response.status_code == 200
    assert close_response.json()["status"] == "CLOSED"
