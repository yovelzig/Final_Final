"""Redis-backed `DistributedLockPort`.

`SET key value NX PX ttl` for acquisition, with a bounded poll-and-retry
loop (never an infinite spin) up to `wait_timeout_seconds`. Release and
extend use atomic Lua scripts keyed on the caller's `owner_id`, so a
worker can never release or extend a lock it does not currently hold -
not even after its own TTL has already expired and a different owner
has since acquired the same key.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

_RELEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""

_EXTEND_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("PEXPIRE", KEYS[1], ARGV[2])
else
    return 0
end
"""

_POLL_INTERVAL_SECONDS = 0.1
_KEY_PREFIX = "finquest:lock:"


class RedisDistributedLock:
    """Satisfies `DistributedLockPort` against a `redis.asyncio.Redis` client.

    The client itself is constructed and owned by the caller (composition
    root) - this class never opens a connection on its own and is safe to
    import at module load time."""

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    def _key(self, key: str) -> str:
        return f"{_KEY_PREFIX}{key}"

    async def acquire(self, *, key: str, owner_id: str, ttl_seconds: int, wait_timeout_seconds: int) -> bool:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        deadline = time.monotonic() + max(0, wait_timeout_seconds)
        redis_key = self._key(key)
        while True:
            acquired = await self._redis.set(redis_key, owner_id, nx=True, px=ttl_seconds * 1000)
            if acquired:
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    async def extend(self, *, key: str, owner_id: str, ttl_seconds: int) -> bool:
        result = await self._redis.eval(_EXTEND_SCRIPT, 1, self._key(key), owner_id, ttl_seconds * 1000)
        return bool(result)

    async def release(self, *, key: str, owner_id: str) -> bool:
        result = await self._redis.eval(_RELEASE_SCRIPT, 1, self._key(key), owner_id)
        return bool(result)


def build_redis_client(redis_url: str) -> Any:
    """The one place allowed to import `redis.asyncio` and open a
    connection pool - called from a composition root only, never at
    import time."""
    import redis.asyncio as redis

    return redis.from_url(redis_url, decode_responses=True)
