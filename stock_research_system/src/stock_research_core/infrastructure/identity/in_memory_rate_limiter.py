"""Process-local, in-memory rate limiter, satisfying `RateLimiterPort`.

**Single-process only.** State is a plain Python dict guarded by an
`asyncio.Lock`, so this limiter only sees requests handled by the exact
worker process it lives in - running the API with more than one
worker/process (or replica) means each one enforces its own independent
limit, which is *not* a correct shared rate limit. This is intentional
for Phase 9 (no Redis is introduced yet); a future
`RedisRateLimiter` implementing the same `RateLimiterPort` is the
documented swap-in for multi-process/multi-replica deployments.

Fixed-window algorithm: each `(key, window_seconds)` bucket resets
`window_seconds` after its first request in the window.
"""

from __future__ import annotations

import asyncio
import time


class InMemoryRateLimiter:
    """Fixed-window, single-process rate limiter satisfying `RateLimiterPort`."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # key -> (window_start_epoch_seconds, count)
        self._buckets: dict[str, tuple[float, int]] = {}

    async def check(self, *, key: str, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        async with self._lock:
            window_start, count = self._buckets.get(key, (now, 0))
            if now - window_start >= window_seconds:
                window_start, count = now, 0
            count += 1
            self._buckets[key] = (window_start, count)
            return count <= limit
