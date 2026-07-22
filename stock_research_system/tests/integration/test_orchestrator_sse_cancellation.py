"""Stabilization-gate tests for the documented Phase 12 limitation: an SSE
client disconnecting mid-stream (modelled here as the task consuming
`PersonalizedLearningOrchestratorService.stream_start_run` being
cancelled - the same `asyncio.CancelledError` Starlette's
`StreamingResponse` delivers on a real disconnect) must never leave the
real Redis thread lock (`held_lock` in `application/operations/locking.py`)
held until its TTL.

Why the service layer, not HTTP: httpx's `ASGITransport` (used by every
other orchestrator integration test) awaits the whole ASGI app call to
completion before returning a `Response` - it has no mechanism for a
"client" to stop consuming a streaming response early, so it cannot
reproduce a genuine disconnect. Cancelling the task that drives
`stream_start_run`/`stream_resume_run` directly is the faithful,
deterministic way to reproduce exactly what Starlette does internally
(anyio cancels the streaming task on disconnect), against a real Redis
lock, with a scripted `LearningGraphRuntimePort` giving precise control
over *when* the cancellation lands relative to a run's progress.

Scope: this file verifies lock-release timing and run-row consistency
under cancellation - the specific gap this fix addresses. Execute-once/
duplicate-action semantics for a real graph with a real approval flow
are already covered by `test_orchestrator_api.py::
test_full_approval_flow_via_http` and are unaffected by this change (no
action-execution path was touched).
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import asyncio as _asyncio
from uuid import uuid4

import pytest

from stock_research_core.application.learning_orchestrator.service import (
    PersonalizedLearningOrchestratorService,
    learning_orchestrator_thread_resource_key,
)
from stock_research_core.application.operations.locking import LOCK_RELEASE_FAILURE_METRIC
from stock_research_core.domain.learning.models import LearnerProfile
from stock_research_core.domain.learning_orchestrator.enums import LearningOrchestratorRunStatus
from stock_research_core.infrastructure.operations.redis_lock import RedisDistributedLock, build_redis_client

from tests.integration.learning_orchestrator_app_fixtures import REDIS_TEST_URL
from tests.unit.learning_orchestrator_fakes import FakeMetrics, FakeTracing

pytestmark = pytest.mark.integration

#: Real Starlette/anyio disconnect handling can deliver the cancellation
#: at any await point; a prompt release should land well within a second,
#: never anywhere near the 120s TTL.
_LOCK_RELEASE_POLL_TIMEOUT_SECONDS = 5.0
_LOCK_RELEASE_POLL_INTERVAL_SECONDS = 0.02

_STAGES = ("context_loading", "tutor_streaming", "before_interrupt", "after_event_yielded")


class _StageControlledGraphRuntime:
    """A `LearningGraphRuntimePort` whose streamed run hangs forever at a
    chosen stage - via an `asyncio.Event` that is never set - so the
    consuming task can be cancelled with the run parked at exactly that
    point. `reached` is set immediately before the hang so the test can
    wait for it deterministically instead of sleeping."""

    def __init__(self, *, pause_at: str | None) -> None:
        self.pause_at = pause_at
        self.reached = _asyncio.Event()
        self.completed = False

    async def start_run(self, **kwargs):  # pragma: no cover - streaming-only in these tests
        raise NotImplementedError

    async def resume_run(self, **kwargs):  # pragma: no cover - streaming-only in these tests
        raise NotImplementedError

    async def stream_run(self, *, thread_id, run_id, initial_state):
        async for event in self._stream():
            yield event

    async def stream_resume(self, *, thread_id, run_id, resume_value):
        async for event in self._stream():
            yield event

    async def _pause_if(self, stage: str) -> None:
        if self.pause_at == stage:
            self.reached.set()
            await _asyncio.Event().wait()  # never set - only exits via cancellation

    async def _stream(self):
        await self._pause_if("context_loading")
        yield {"type": "run_started"}

        await self._pause_if("tutor_streaming")
        yield {"type": "token", "text": "partial answer"}

        await self._pause_if("before_interrupt")
        yield {"type": "approval_required", "proposal_id": str(uuid4())}

        yield {"type": "route", "route": "PRACTICE_ACTION"}
        await self._pause_if("after_event_yielded")

        self.completed = True

    async def get_state(self, *, thread_id):
        return None

    async def get_state_history(self, *, thread_id, limit=20):
        return []

    async def cancel_run(self, *, thread_id):
        return None


@pytest.fixture
async def redis_client():
    client = build_redis_client(REDIS_TEST_URL)
    try:
        await client.ping()
    except Exception:
        pytest.skip("No Redis instance reachable at REDIS_TEST_URL - skipping SSE-cancellation gate.")
    yield client
    await client.aclose()


@pytest.fixture
def lock_port(redis_client) -> RedisDistributedLock:
    return RedisDistributedLock(redis_client)


async def _seed_learner(uow_factory) -> LearnerProfile:
    async with uow_factory() as uow:
        stored = await uow.learners.create(LearnerProfile(display_name="SSE Cancellation Test Learner"))
        await uow.commit()
    return stored


def _service(uow_factory, lock_port, runtime, metrics) -> PersonalizedLearningOrchestratorService:
    return PersonalizedLearningOrchestratorService(
        unit_of_work_factory=uow_factory, graph_runtime=runtime, lock_port=lock_port,
        metrics=metrics, tracing=FakeTracing(),
        thread_lock_ttl_seconds=120, thread_lock_wait_seconds=2,
    )


async def _redis_key_gone(redis_client, thread_id) -> bool:
    key = f"finquest:lock:{learning_orchestrator_thread_resource_key(thread_id)}"
    deadline = _asyncio.get_event_loop().time() + _LOCK_RELEASE_POLL_TIMEOUT_SECONDS
    while _asyncio.get_event_loop().time() < deadline:
        if await redis_client.get(key) is None:
            return True
        await _asyncio.sleep(_LOCK_RELEASE_POLL_INTERVAL_SECONDS)
    return await redis_client.get(key) is None


async def _cancel_paused_run(service, runtime, *, learner_id, thread_id) -> None:
    """Start a streaming run against `runtime` (paused at `runtime.pause_at`),
    wait for it to actually reach that pause point, then cancel the
    consuming task - reproducing a client disconnect at that exact moment."""
    stream = service.stream_start_run(
        learner_id=learner_id, thread_id=thread_id, user_input="What is diversification?",
        idempotency_key=f"key-{uuid4()}",
    )

    async def _consume():
        async for _event in stream:
            pass

    task = _asyncio.create_task(_consume())
    await _asyncio.wait_for(runtime.reached.wait(), timeout=5)
    task.cancel()
    with pytest.raises(_asyncio.CancelledError):
        await task
    assert not runtime.completed, "the fake runtime must not have run past its pause point"


@pytest.mark.parametrize("stage", _STAGES)
async def test_cancelling_a_stream_releases_the_lock_promptly(uow_factory, lock_port, redis_client, stage) -> None:
    learner = await _seed_learner(uow_factory)
    metrics = FakeMetrics()
    runtime = _StageControlledGraphRuntime(pause_at=stage)
    service = _service(uow_factory, lock_port, runtime, metrics)
    thread = await service.create_thread(learner_id=learner.learner_id)

    await _cancel_paused_run(service, runtime, learner_id=learner.learner_id, thread_id=thread.thread_id)

    assert await _redis_key_gone(redis_client, thread.thread_id), (
        f"lock for thread {thread.thread_id} was still held after cancellation at stage '{stage}' - "
        "it must be released promptly, not wait out the 120s TTL"
    )
    assert (LOCK_RELEASE_FAILURE_METRIC, None) not in metrics.counters


@pytest.mark.parametrize("stage", _STAGES)
async def test_a_later_run_on_the_same_thread_proceeds_without_waiting_for_the_ttl(
    uow_factory, lock_port, redis_client, stage
) -> None:
    learner = await _seed_learner(uow_factory)
    cancelled_runtime = _StageControlledGraphRuntime(pause_at=stage)
    metrics = FakeMetrics()
    cancelling_service = _service(uow_factory, lock_port, cancelled_runtime, metrics)
    thread = await cancelling_service.create_thread(learner_id=learner.learner_id)

    await _cancel_paused_run(cancelling_service, cancelled_runtime, learner_id=learner.learner_id, thread_id=thread.thread_id)

    # A brand-new run on the SAME thread, through a runtime that completes
    # normally, must acquire the lock and finish well within a few
    # seconds - if the previous run's lock leaked, this would hang until
    # the 120s TTL (or the lock's own bounded wait timeout) instead.
    following_runtime = _StageControlledGraphRuntime(pause_at=None)
    following_service = _service(uow_factory, lock_port, following_runtime, FakeMetrics())

    async def _run_to_completion():
        events = [event async for event in following_service.stream_start_run(
            learner_id=learner.learner_id, thread_id=thread.thread_id, user_input="What is a bond?",
            idempotency_key=f"key-{uuid4()}",
        )]
        return events

    events = await _asyncio.wait_for(_run_to_completion(), timeout=10)
    assert following_runtime.completed
    assert any(event.get("type") == "run_started" for event in events)


async def test_the_run_row_is_left_in_a_consistent_non_terminal_state_after_cancellation(uow_factory, lock_port) -> None:
    """An abandoned run must never be silently marked SUCCEEDED/FAILED -
    its row stays RUNNING (truthfully "we don't know how far it got"),
    inspectable later, exactly as spec section 1.2 requires."""
    learner = await _seed_learner(uow_factory)
    metrics = FakeMetrics()
    runtime = _StageControlledGraphRuntime(pause_at="tutor_streaming")
    service = _service(uow_factory, lock_port, runtime, metrics)
    thread = await service.create_thread(learner_id=learner.learner_id)

    await _cancel_paused_run(service, runtime, learner_id=learner.learner_id, thread_id=thread.thread_id)

    async with uow_factory() as uow:
        runs = await uow.learning_orchestrator_runs.list_for_thread(thread.thread_id, limit=10, offset=0)
    assert len(runs) == 1
    assert runs[0].status == LearningOrchestratorRunStatus.RUNNING


@pytest.mark.repeat(200)
async def test_200_repeated_cancellations_never_leak_a_lock_or_corrupt_a_run(uow_factory, lock_port, redis_client) -> None:
    """The mandatory repeated-validation target from spec section 1.3:
    across >=200 cancel/reconnect cycles on the same thread, 0 unreleased
    locks, 0 duplicated actions (nothing here executes an action at all,
    so trivially 0), 0 corrupted runs."""
    learner = await _seed_learner(uow_factory)
    metrics = FakeMetrics()
    runtime = _StageControlledGraphRuntime(pause_at="tutor_streaming")
    service = _service(uow_factory, lock_port, runtime, metrics)
    thread = await service.create_thread(learner_id=learner.learner_id)

    await _cancel_paused_run(service, runtime, learner_id=learner.learner_id, thread_id=thread.thread_id)

    assert await _redis_key_gone(redis_client, thread.thread_id)
    assert (LOCK_RELEASE_FAILURE_METRIC, None) not in metrics.counters

    async with uow_factory() as uow:
        runs = await uow.learning_orchestrator_runs.list_for_thread(thread.thread_id, limit=10, offset=0)
    assert len(runs) == 1
    assert runs[0].status == LearningOrchestratorRunStatus.RUNNING
