"""Integration tests for `RedisDistributedLock` against a real Redis
instance: two workers cannot execute the same resource-conflicting job
simultaneously, unrelated resources run concurrently, expired locks can
be reacquired, and ownership is enforced for release/extend.

Requires `REDIS_URL` (or the default `redis://localhost:6379/0`) to be
reachable; skipped, not failed, when it is not.
"""

from __future__ import annotations

import asyncio

import pytest

from stock_research_core.infrastructure.operations.config import OperationsSettings
from stock_research_core.infrastructure.operations.redis_lock import RedisDistributedLock, build_redis_client

pytestmark = pytest.mark.integration


@pytest.fixture
async def redis_client():
    client = build_redis_client(OperationsSettings().redis_url)
    try:
        await client.ping()
    except Exception:
        pytest.skip("No Redis instance reachable - skipping distributed-lock integration tests.")
    yield client
    await client.aclose()


@pytest.fixture
def lock(redis_client) -> RedisDistributedLock:
    return RedisDistributedLock(redis_client)


class TestRedisDistributedLock:
    async def test_acquire_and_release(self, lock: RedisDistributedLock) -> None:
        key = "test-resource-a"
        acquired = await lock.acquire(key=key, owner_id="owner-1", ttl_seconds=5, wait_timeout_seconds=1)
        assert acquired
        released = await lock.release(key=key, owner_id="owner-1")
        assert released

    async def test_competing_acquire_fails_while_held(self, lock: RedisDistributedLock) -> None:
        key = "test-resource-b"
        assert await lock.acquire(key=key, owner_id="owner-1", ttl_seconds=5, wait_timeout_seconds=1)
        competing = await lock.acquire(key=key, owner_id="owner-2", ttl_seconds=5, wait_timeout_seconds=1)
        assert not competing
        await lock.release(key=key, owner_id="owner-1")

    async def test_unrelated_resource_runs_concurrently(self, lock: RedisDistributedLock) -> None:
        assert await lock.acquire(key="test-resource-c", owner_id="owner-1", ttl_seconds=5, wait_timeout_seconds=1)
        assert await lock.acquire(key="test-resource-d", owner_id="owner-2", ttl_seconds=5, wait_timeout_seconds=1)
        await lock.release(key="test-resource-c", owner_id="owner-1")
        await lock.release(key="test-resource-d", owner_id="owner-2")

    async def test_non_owner_cannot_release(self, lock: RedisDistributedLock) -> None:
        key = "test-resource-e"
        await lock.acquire(key=key, owner_id="owner-1", ttl_seconds=5, wait_timeout_seconds=1)
        assert not await lock.release(key=key, owner_id="owner-2")
        assert await lock.release(key=key, owner_id="owner-1")

    async def test_non_owner_cannot_extend(self, lock: RedisDistributedLock) -> None:
        key = "test-resource-f"
        await lock.acquire(key=key, owner_id="owner-1", ttl_seconds=5, wait_timeout_seconds=1)
        assert not await lock.extend(key=key, owner_id="owner-2", ttl_seconds=10)
        assert await lock.extend(key=key, owner_id="owner-1", ttl_seconds=10)
        await lock.release(key=key, owner_id="owner-1")

    async def test_expired_lock_can_be_reacquired(self, lock: RedisDistributedLock) -> None:
        key = "test-resource-g"
        await lock.acquire(key=key, owner_id="owner-1", ttl_seconds=1, wait_timeout_seconds=1)
        await asyncio.sleep(1.5)
        reacquired = await lock.acquire(key=key, owner_id="owner-2", ttl_seconds=5, wait_timeout_seconds=1)
        assert reacquired
        await lock.release(key=key, owner_id="owner-2")

    async def test_two_workers_cannot_run_the_same_conflicting_job_simultaneously(self, lock: RedisDistributedLock) -> None:
        key = "test-resource-h"
        in_flight = 0
        max_observed = 0

        async def _run(owner_id: str) -> None:
            nonlocal in_flight, max_observed
            acquired = await lock.acquire(key=key, owner_id=owner_id, ttl_seconds=5, wait_timeout_seconds=2)
            if not acquired:
                return
            try:
                in_flight += 1
                max_observed = max(max_observed, in_flight)
                await asyncio.sleep(0.2)
            finally:
                in_flight -= 1
                await lock.release(key=key, owner_id=owner_id)

        await asyncio.gather(_run("owner-1"), _run("owner-2"), _run("owner-3"))
        assert max_observed == 1
