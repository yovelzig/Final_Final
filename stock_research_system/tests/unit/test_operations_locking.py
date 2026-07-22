"""Unit tests for `held_lock` and the resource-key builders
(`application.operations.locking`), using a fake `DistributedLockPort`
so no real Redis is required."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import LockAcquisitionError
from stock_research_core.application.operations.locking import (
    LOCK_RELEASE_FAILURE_METRIC,
    held_lock,
    knowledge_curriculum_refresh_resource_key,
    knowledge_document_reembed_resource_key,
    market_security_resource_key,
    portfolio_valuation_resource_key,
    retrieval_evaluation_resource_key,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeLock:
    def __init__(self, *, always_fail: bool = False) -> None:
        self._held: dict[str, str] = {}
        self._always_fail = always_fail
        self.acquire_calls = 0
        self.release_calls = 0

    async def acquire(self, *, key: str, owner_id: str, ttl_seconds: int, wait_timeout_seconds: int) -> bool:
        self.acquire_calls += 1
        if self._always_fail or key in self._held:
            return False
        self._held[key] = owner_id
        return True

    async def extend(self, *, key: str, owner_id: str, ttl_seconds: int) -> bool:
        return self._held.get(key) == owner_id

    async def release(self, *, key: str, owner_id: str) -> bool:
        self.release_calls += 1
        if self._held.get(key) != owner_id:
            return False
        del self._held[key]
        return True


class TestHeldLock:
    @pytest.mark.asyncio
    async def test_none_key_is_a_no_op(self) -> None:
        lock = FakeLock()
        ran = False
        async with held_lock(lock, key=None, owner_id="owner-1"):
            ran = True
        assert ran
        assert lock.acquire_calls == 0

    @pytest.mark.asyncio
    async def test_lock_is_acquired_and_released_on_success(self) -> None:
        lock = FakeLock()
        async with held_lock(lock, key="res-a", owner_id="owner-1"):
            assert "res-a" in lock._held
        assert "res-a" not in lock._held

    @pytest.mark.asyncio
    async def test_lock_is_released_after_handler_failure(self) -> None:
        lock = FakeLock()
        with pytest.raises(RuntimeError):
            async with held_lock(lock, key="res-a", owner_id="owner-1"):
                raise RuntimeError("handler blew up")
        assert "res-a" not in lock._held

    @pytest.mark.asyncio
    async def test_unacquirable_lock_raises_lock_acquisition_error(self) -> None:
        lock = FakeLock(always_fail=True)
        with pytest.raises(LockAcquisitionError):
            async with held_lock(lock, key="res-a", owner_id="owner-1"):
                pytest.fail("must not run when the lock cannot be acquired")

    @pytest.mark.asyncio
    async def test_conflicting_resource_blocks_second_owner(self) -> None:
        lock = FakeLock()
        async with held_lock(lock, key="res-a", owner_id="owner-1"):
            with pytest.raises(LockAcquisitionError):
                async with held_lock(lock, key="res-a", owner_id="owner-2"):
                    pytest.fail("must not run while owner-1 still holds the lock")

    @pytest.mark.asyncio
    async def test_unrelated_resources_do_not_block_each_other(self) -> None:
        lock = FakeLock()
        async with held_lock(lock, key="res-a", owner_id="owner-1"):
            ran = False
            async with held_lock(lock, key="res-b", owner_id="owner-2"):
                ran = True
            assert ran


class _RecordingMetrics:
    def __init__(self) -> None:
        self.counters: list[tuple[str, dict[str, str] | None]] = []

    def increment_counter(self, name: str, *, value: float = 1.0, labels=None) -> None:
        self.counters.append((name, labels))

    def set_gauge(self, name, value, *, labels=None) -> None:
        pass

    def observe_histogram(self, name, value, *, labels=None) -> None:
        pass

    def time_operation(self, name, *, labels=None):
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            yield

        return _cm()


class SlowReleaseLock(FakeLock):
    """A `release()` that takes a controllable, observable amount of time -
    for proving `held_lock`'s cleanup survives a second cancellation
    landing while release is in flight (the anyio "sticky cancel scope"
    scenario Starlette's real disconnect handling can produce)."""

    def __init__(self, *, release_delay_seconds: float = 0.15, **kwargs) -> None:
        super().__init__(**kwargs)
        self.release_delay_seconds = release_delay_seconds
        self.release_started = asyncio.Event()
        self.release_finished = asyncio.Event()

    async def release(self, *, key: str, owner_id: str) -> bool:
        self.release_started.set()
        await asyncio.sleep(self.release_delay_seconds)
        result = await super().release(key=key, owner_id=owner_id)
        self.release_finished.set()
        return result


class HangingReleaseLock(FakeLock):
    """A `release()` that never returns - simulates Redis being genuinely
    unreachable during cleanup, to prove `release_timeout_seconds` bounds
    the wait instead of hanging the caller forever."""

    async def release(self, *, key: str, owner_id: str) -> bool:
        await asyncio.sleep(3600)
        return True  # pragma: no cover - never reached


class TestHeldLockCancellationSafety:
    """Regression coverage for the SSE-cancellation stabilization gate
    (Phase 13 section 1): a cancellation landing *during* `held_lock`'s
    own cleanup must not abort the release call itself."""

    @pytest.mark.asyncio
    async def test_release_survives_a_second_cancellation_landing_during_cleanup(self) -> None:
        lock = SlowReleaseLock()
        metrics = _RecordingMetrics()
        entered = asyncio.Event()

        async def _body() -> None:
            async with held_lock(lock, key="res-a", owner_id="owner-1", metrics=metrics, release_timeout_seconds=2):
                entered.set()
                await asyncio.Event().wait()  # hangs until cancelled

        task = asyncio.create_task(_body())
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()  # first cancellation - unwinds into `held_lock`'s `finally`

        await asyncio.wait_for(lock.release_started.wait(), timeout=1)
        task.cancel()  # second cancellation - lands while the shielded release is in flight

        with pytest.raises(asyncio.CancelledError):
            await task

        # The critical guarantee: the shielded release call itself was
        # never aborted by the second cancellation, so it completed and
        # the key really is gone - even though `held_lock` could not
        # *synchronously confirm* that before the second cancellation cut
        # its own wait short, which is exactly what the metric reports.
        await asyncio.wait_for(lock.release_finished.wait(), timeout=1)
        assert "res-a" not in lock._held
        assert metrics.counters == [(LOCK_RELEASE_FAILURE_METRIC, None)]

    @pytest.mark.asyncio
    async def test_a_hanging_release_is_bounded_by_release_timeout_and_recorded(self) -> None:
        lock = HangingReleaseLock()
        metrics = _RecordingMetrics()

        async def _body() -> None:
            async with held_lock(lock, key="res-a", owner_id="owner-1", metrics=metrics, release_timeout_seconds=0.05):
                pass

        await asyncio.wait_for(_body(), timeout=2)  # would hit the outer 2s bound if release_timeout_seconds did nothing
        assert metrics.counters == [(LOCK_RELEASE_FAILURE_METRIC, None)]

    @pytest.mark.asyncio
    async def test_release_failure_never_masks_the_original_exception(self) -> None:
        lock = HangingReleaseLock()
        metrics = _RecordingMetrics()

        async def _body() -> None:
            async with held_lock(lock, key="res-a", owner_id="owner-1", metrics=metrics, release_timeout_seconds=0.05):
                raise RuntimeError("handler blew up")

        with pytest.raises(RuntimeError, match="handler blew up"):
            await asyncio.wait_for(_body(), timeout=2)
        assert metrics.counters == [(LOCK_RELEASE_FAILURE_METRIC, None)]


class TestResourceKeyBuilders:
    def test_market_security_key_is_stable_and_scoped(self) -> None:
        security_id = uuid4()
        key1 = market_security_resource_key(security_id=security_id, source_name="yfinance", interval="1d")
        key2 = market_security_resource_key(security_id=security_id, source_name="yfinance", interval="1d")
        key3 = market_security_resource_key(security_id=security_id, source_name="yfinance", interval="1h")
        assert key1 == key2
        assert key1 != key3

    def test_portfolio_valuation_key_includes_as_of(self) -> None:
        portfolio_id = uuid4()
        key1 = portfolio_valuation_resource_key(portfolio_id=portfolio_id, as_of=NOW)
        key2 = portfolio_valuation_resource_key(portfolio_id=portfolio_id, as_of=NOW.replace(hour=1))
        assert key1 != key2

    def test_knowledge_curriculum_refresh_key_is_constant(self) -> None:
        assert knowledge_curriculum_refresh_resource_key() == knowledge_curriculum_refresh_resource_key()

    def test_knowledge_document_reembed_key_is_scoped_per_document(self) -> None:
        doc_a, doc_b = uuid4(), uuid4()
        assert knowledge_document_reembed_resource_key(document_id=doc_a) != knowledge_document_reembed_resource_key(
            document_id=doc_b
        )

    def test_retrieval_evaluation_key_is_scoped_by_dataset_and_top_k(self) -> None:
        key1 = retrieval_evaluation_resource_key(dataset="default_v1", top_k=5)
        key2 = retrieval_evaluation_resource_key(dataset="default_v1", top_k=10)
        assert key1 != key2
