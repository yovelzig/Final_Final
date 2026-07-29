"""Unit tests for `RedisAccountResearchLimiter` (spec G2D2 section 18;
G2D2/H1 correction pass, section 8: atomic per-account concurrency
acquire/release) against a minimal in-memory fake Redis client - no real
Redis required.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from stock_research_core.infrastructure.live_research.redis_account_rate_limiter import RedisAccountResearchLimiter


class _FakeRedis:
    """Emulates just the two Redis primitives the limiter's Lua scripts
    use - a fixed-window INCR/EXPIRE counter (hourly usage) and a scored
    sorted set (the per-account concurrency slot) - dispatched by
    inspecting which script text was passed, mirroring how a real Redis
    server would execute either script atomically. `ZREMRANGEBYSCORE` is
    checked before the (textually overlapping) `ZREM` release script."""

    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.zsets: dict[str, dict[str, float]] = {}

    async def eval(self, script: str, numkeys: int, key: str, *args) -> int:
        if "ZREMRANGEBYSCORE" in script:
            now, ttl_seconds, limit, reservation_id = args
            now, ttl_seconds, limit = float(now), float(ttl_seconds), int(limit)
            zset = self.zsets.setdefault(key, {})
            for member in [m for m, score in zset.items() if score <= now]:
                del zset[member]
            expiry = now + ttl_seconds
            if reservation_id in zset:
                zset[reservation_id] = expiry
                return 1
            if len(zset) >= limit:
                return 0
            zset[reservation_id] = expiry
            return 1

        if "ZREM" in script:
            (reservation_id,) = args
            self.zsets.setdefault(key, {}).pop(reservation_id, None)
            return 1

        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]


async def test_allows_requests_within_both_limits() -> None:
    redis = _FakeRedis()
    limiter = RedisAccountResearchLimiter(
        redis_client=redis, concurrent_limit=2, hourly_limit=5, concurrent_window_seconds=600,
    )
    account_id = uuid4()
    decision = await limiter.try_acquire(account_id=account_id, reservation_id="run-1")
    assert decision.allowed is True
    assert decision.reason is None


async def test_second_concurrent_reservation_is_rejected_while_first_is_outstanding() -> None:
    """One accepted job owns one slot - a second, distinct reservation
    for the same account is rejected while the first is still held."""
    redis = _FakeRedis()
    limiter = RedisAccountResearchLimiter(
        redis_client=redis, concurrent_limit=1, hourly_limit=100, concurrent_window_seconds=600,
    )
    account_id = uuid4()
    first = await limiter.try_acquire(account_id=account_id, reservation_id="run-1")
    second = await limiter.try_acquire(account_id=account_id, reservation_id="run-2")
    assert first.allowed is True
    assert second.allowed is False
    assert second.reason == "CONCURRENT_LIMIT_REACHED"


async def test_after_release_another_reservation_is_accepted_immediately() -> None:
    redis = _FakeRedis()
    limiter = RedisAccountResearchLimiter(
        redis_client=redis, concurrent_limit=1, hourly_limit=100, concurrent_window_seconds=600,
    )
    account_id = uuid4()
    first = await limiter.try_acquire(account_id=account_id, reservation_id="run-1")
    assert first.allowed is True

    await limiter.release(account_id=account_id, reservation_id="run-1")

    second = await limiter.try_acquire(account_id=account_id, reservation_id="run-2")
    assert second.allowed is True


async def test_duplicate_release_is_harmless() -> None:
    redis = _FakeRedis()
    limiter = RedisAccountResearchLimiter(
        redis_client=redis, concurrent_limit=1, hourly_limit=100, concurrent_window_seconds=600,
    )
    account_id = uuid4()
    await limiter.try_acquire(account_id=account_id, reservation_id="run-1")

    await limiter.release(account_id=account_id, reservation_id="run-1")
    await limiter.release(account_id=account_id, reservation_id="run-1")  # duplicate - must not raise

    second = await limiter.try_acquire(account_id=account_id, reservation_id="run-2")
    assert second.allowed is True


async def test_releasing_a_reservation_that_was_never_acquired_is_harmless() -> None:
    redis = _FakeRedis()
    limiter = RedisAccountResearchLimiter(
        redis_client=redis, concurrent_limit=1, hourly_limit=100, concurrent_window_seconds=600,
    )
    await limiter.release(account_id=uuid4(), reservation_id="never-acquired")  # must not raise


async def test_denies_once_hourly_limit_is_exceeded() -> None:
    redis = _FakeRedis()
    limiter = RedisAccountResearchLimiter(
        redis_client=redis, concurrent_limit=100, hourly_limit=1, concurrent_window_seconds=600,
    )
    account_id = uuid4()
    first = await limiter.try_acquire(account_id=account_id, reservation_id="run-1")
    second = await limiter.try_acquire(account_id=account_id, reservation_id="run-2")
    assert first.allowed is True
    assert second.allowed is False
    assert second.reason == "HOURLY_LIMIT_REACHED"


async def test_hourly_rejection_rolls_back_the_concurrent_reservation_it_already_made() -> None:
    """`try_acquire` reserves the concurrency slot before checking the
    hourly counter - an hourly rejection must not leave that slot
    permanently consumed."""
    redis = _FakeRedis()
    limiter = RedisAccountResearchLimiter(
        redis_client=redis, concurrent_limit=2, hourly_limit=1, concurrent_window_seconds=600,
    )
    account_id = uuid4()
    first = await limiter.try_acquire(account_id=account_id, reservation_id="run-1")
    assert first.allowed is True

    second = await limiter.try_acquire(account_id=account_id, reservation_id="run-2")
    assert second.allowed is False
    assert second.reason == "HOURLY_LIMIT_REACHED"

    # The concurrency slot reserved for run-2 must have been rolled back:
    # only run-1's reservation remains held for this account.
    assert set(redis.zsets[f"finquest:live-research-rate-limit:concurrent:{account_id}"]) == {"run-1"}


async def test_limits_are_per_account() -> None:
    redis = _FakeRedis()
    limiter = RedisAccountResearchLimiter(
        redis_client=redis, concurrent_limit=1, hourly_limit=1, concurrent_window_seconds=600,
    )
    first_account, second_account = uuid4(), uuid4()
    first_decision = await limiter.try_acquire(account_id=first_account, reservation_id="run-1")
    second_decision = await limiter.try_acquire(account_id=second_account, reservation_id="run-2")
    assert first_decision.allowed is True
    assert second_decision.allowed is True


@pytest.mark.parametrize("bad_kwargs", [{"concurrent_limit": 0}, {"hourly_limit": 0}, {"concurrent_window_seconds": 0}])
def test_rejects_invalid_construction(bad_kwargs: dict) -> None:
    kwargs = {"redis_client": _FakeRedis(), "concurrent_limit": 1, "hourly_limit": 1, "concurrent_window_seconds": 600}
    kwargs.update(bad_kwargs)
    with pytest.raises(ValueError):
        RedisAccountResearchLimiter(**kwargs)
