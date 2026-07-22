"""Resource-key conventions and the owner-safe lock-acquisition helper
used by `BackgroundJobService.execute_job`.

Each job type that touches a shared, conflict-sensitive resource (a
security's price history, one portfolio's valuation, the shared
knowledge base) is assigned a deterministic resource key by the job
registry. Two jobs sharing a resource key can never run concurrently;
jobs with different resource keys always can.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING, AsyncIterator
from uuid import UUID

from stock_research_core.application.exceptions import LockAcquisitionError
from stock_research_core.application.operations.ports import DistributedLockPort

if TYPE_CHECKING:
    from stock_research_core.application.operations.ports import MetricsPort

#: Bounded, conservative defaults - never infinite. Individual job types
#: may override via the registry entry if a longer-running handler needs it.
DEFAULT_LOCK_TTL_SECONDS = 300
DEFAULT_LOCK_WAIT_TIMEOUT_SECONDS = 5

#: Bound on the *cleanup-time* release call itself (distinct from
#: `wait_timeout_seconds`, which bounds waiting to *acquire*). Shielded from
#: outer cancellation - see `held_lock` - so a client disconnect mid-release
#: can never abort the release before it gets this long to finish. Kept
#: short: if Redis is genuinely unreachable, the lock's own TTL is the
#: backstop, not a longer wait here.
DEFAULT_RELEASE_TIMEOUT_SECONDS = 5.0

#: Emitted by `held_lock` only when the shielded release itself fails or
#: times out (i.e. cleanup could not confirm the lock was dropped) - not on
#: every cancellation, most of which release cleanly. No case/run/key labels
#: (spec: bounded-label metrics only).
LOCK_RELEASE_FAILURE_METRIC = "finquest_sse_lock_cleanup_failures_total"

__all__ = [
    "DEFAULT_LOCK_TTL_SECONDS",
    "DEFAULT_LOCK_WAIT_TIMEOUT_SECONDS",
    "DEFAULT_RELEASE_TIMEOUT_SECONDS",
    "LOCK_RELEASE_FAILURE_METRIC",
    "LockAcquisitionError",
    "held_lock",
    "market_security_resource_key",
    "portfolio_valuation_resource_key",
    "knowledge_curriculum_refresh_resource_key",
    "knowledge_document_reembed_resource_key",
    "retrieval_evaluation_resource_key",
]


def market_security_resource_key(*, security_id: UUID, source_name: str, interval: str) -> str:
    return f"market-security:{security_id}:{source_name}:{interval}"


def portfolio_valuation_resource_key(*, portfolio_id: UUID, as_of: datetime) -> str:
    return f"portfolio-valuation:{portfolio_id}:{as_of.isoformat()}"


def knowledge_curriculum_refresh_resource_key() -> str:
    return "knowledge-curriculum-refresh"


def knowledge_document_reembed_resource_key(*, document_id: UUID) -> str:
    return f"knowledge-document-reembed:{document_id}"


def retrieval_evaluation_resource_key(*, dataset: str, top_k: int) -> str:
    return f"retrieval-evaluation:{dataset}:{top_k}"


@asynccontextmanager
async def held_lock(
    lock_port: DistributedLockPort,
    *,
    key: str | None,
    owner_id: str,
    ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
    wait_timeout_seconds: int = DEFAULT_LOCK_WAIT_TIMEOUT_SECONDS,
    release_timeout_seconds: float = DEFAULT_RELEASE_TIMEOUT_SECONDS,
    metrics: "MetricsPort | None" = None,
) -> AsyncIterator[None]:
    """Acquire `key` for the duration of the block, always releasing it on
    the way out - success or failure - and only ever releasing the lock
    this exact `owner_id` acquired. A `None` key (no shared resource) is a
    no-op - the block always runs.

    The release itself is shielded from the *caller's* cancellation (e.g. a
    disconnected SSE client cancelling the streaming task) and bounded by
    `release_timeout_seconds`: without the shield, a cancellation landing
    exactly inside this `finally` could abort the release call itself,
    leaving the Redis key held until its TTL expires instead of being
    dropped immediately. The shield only protects the release call - it
    never suppresses or delays the cancellation being raised into the
    caller once cleanup is done."""
    if key is None:
        yield
        return

    acquired = await lock_port.acquire(
        key=key, owner_id=owner_id, ttl_seconds=ttl_seconds, wait_timeout_seconds=wait_timeout_seconds
    )
    if not acquired:
        raise LockAcquisitionError(f"Could not acquire resource lock '{key}': another job is running.")
    try:
        yield
    finally:
        try:
            await asyncio.wait_for(
                asyncio.shield(lock_port.release(key=key, owner_id=owner_id)),
                timeout=release_timeout_seconds,
            )
        except asyncio.CancelledError:
            # The *release call itself* was cancelled (its own task was
            # torn down, not merely our caller) or exceeded its bound while
            # shielded - cleanup could not confirm the key was dropped.
            # The lock's TTL is the backstop; record it so this is visible
            # rather than silently relying on that backstop.
            if metrics is not None:
                metrics.increment_counter(LOCK_RELEASE_FAILURE_METRIC)
        except Exception:  # noqa: BLE001 - never let cleanup mask the original error
            if metrics is not None:
                metrics.increment_counter(LOCK_RELEASE_FAILURE_METRIC)
