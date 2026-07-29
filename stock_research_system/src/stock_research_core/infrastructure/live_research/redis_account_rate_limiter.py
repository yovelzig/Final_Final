"""Redis-backed `AccountResearchRateLimiterPort` (spec G2D2 section 18;
G2D2/H1 correction pass, section 8).

Two independent mechanisms per account, both enforced before any
`LIVE_RESEARCH_RUN_EXECUTION` job is created:

- an hourly counter (`LIVE_RESEARCH_PER_ACCOUNT_HOURLY_LIMIT`), a
  standard fixed one-hour window, purely cumulative - never released,
  and untouched by this correction pass; and
- a per-account "concurrent" slot (`LIVE_RESEARCH_PER_ACCOUNT_CONCURRENT_
  LIMIT`), now a true atomic acquire/release contract: one accepted job
  owns one slot, keyed by the caller's own `reservation_id` (the Coach
  run's `run_id`, known before the `BackgroundJob` exists). A Redis
  sorted set per account holds one member per outstanding reservation,
  scored by its own expiry timestamp - `try_acquire` atomically prunes
  expired members (the leak-recovery backstop, now secondary rather than
  the only release mechanism) before counting and reserving, all inside
  one Lua script so concurrent callers across processes never race past
  the limit. `release` removes exactly one reservation and is inherently
  idempotent (`ZREM` on a member that is not present is a no-op).

The hourly counter still uses the original atomic "INCR, EXPIRE only on
first increment" Lua script `RedisDistributedLock` established the style
for; it is deliberately left as a bare counter since it must never be
released early.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from stock_research_core.application.live_research.rate_limit_ports import RateLimitDecision

_INCREMENT_WITH_EXPIRY_SCRIPT = """
local current = redis.call("INCR", KEYS[1])
if current == 1 then
    redis.call("EXPIRE", KEYS[1], ARGV[1])
end
return current
"""

#: KEYS[1] = concurrent_key
#: ARGV[1] = now (epoch seconds), ARGV[2] = ttl_seconds (leak-recovery
#: backstop), ARGV[3] = concurrent_limit, ARGV[4] = reservation_id
_ACQUIRE_CONCURRENT_SLOT_SCRIPT = """
redis.call("ZREMRANGEBYSCORE", KEYS[1], "-inf", ARGV[1])
local expiry = tonumber(ARGV[1]) + tonumber(ARGV[2])
if redis.call("ZSCORE", KEYS[1], ARGV[4]) then
    -- Idempotent re-acquire of a reservation this same caller already
    -- holds - refresh its expiry without counting it a second time.
    redis.call("ZADD", KEYS[1], expiry, ARGV[4])
    redis.call("EXPIRE", KEYS[1], ARGV[2])
    return 1
end
local count = redis.call("ZCARD", KEYS[1])
if count >= tonumber(ARGV[3]) then
    return 0
end
redis.call("ZADD", KEYS[1], expiry, ARGV[4])
redis.call("EXPIRE", KEYS[1], ARGV[2])
return 1
"""

#: KEYS[1] = concurrent_key, ARGV[1] = reservation_id
_RELEASE_CONCURRENT_SLOT_SCRIPT = """
redis.call("ZREM", KEYS[1], ARGV[1])
return 1
"""

_KEY_PREFIX = "finquest:live-research-rate-limit:"
_HOURLY_WINDOW_SECONDS = 3600

_REASON_CONCURRENT_LIMIT = "CONCURRENT_LIMIT_REACHED"
_REASON_HOURLY_LIMIT = "HOURLY_LIMIT_REACHED"


class RedisAccountResearchLimiter:
    def __init__(
        self, *, redis_client: Any, concurrent_limit: int, hourly_limit: int, concurrent_window_seconds: int,
    ) -> None:
        if concurrent_limit < 1:
            raise ValueError("concurrent_limit must be at least 1")
        if hourly_limit < 1:
            raise ValueError("hourly_limit must be at least 1")
        if concurrent_window_seconds < 1:
            raise ValueError("concurrent_window_seconds must be at least 1")
        self._redis = redis_client
        self._concurrent_limit = concurrent_limit
        self._hourly_limit = hourly_limit
        self._concurrent_window_seconds = concurrent_window_seconds

    @staticmethod
    def _concurrent_key(account_id: UUID) -> str:
        return f"{_KEY_PREFIX}concurrent:{account_id}"

    async def try_acquire(self, *, account_id: UUID, reservation_id: str) -> RateLimitDecision:
        concurrent_key = self._concurrent_key(account_id)
        hourly_key = f"{_KEY_PREFIX}hourly:{account_id}"

        acquired = await self._redis.eval(
            _ACQUIRE_CONCURRENT_SLOT_SCRIPT, 1, concurrent_key,
            time.time(), self._concurrent_window_seconds, self._concurrent_limit, reservation_id,
        )
        if not int(acquired):
            return RateLimitDecision(allowed=False, reason=_REASON_CONCURRENT_LIMIT)

        hourly_count = await self._redis.eval(_INCREMENT_WITH_EXPIRY_SCRIPT, 1, hourly_key, _HOURLY_WINDOW_SECONDS)
        if int(hourly_count) > self._hourly_limit:
            # The concurrency slot was already reserved above - an hourly
            # rejection must still roll it back, since this request was
            # never accepted.
            await self.release(account_id=account_id, reservation_id=reservation_id)
            return RateLimitDecision(allowed=False, reason=_REASON_HOURLY_LIMIT)

        return RateLimitDecision(allowed=True)

    async def release(self, *, account_id: UUID, reservation_id: str) -> None:
        await self._redis.eval(_RELEASE_CONCURRENT_SLOT_SCRIPT, 1, self._concurrent_key(account_id), reservation_id)
