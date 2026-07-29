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
import hashlib
from contextlib import asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING, AsyncIterator
from uuid import UUID

from stock_research_core.application.exceptions import LockAcquisitionError
from stock_research_core.application.operations.ports import DistributedLockPort, JobExecutionContext

if TYPE_CHECKING:
    from stock_research_core.application.operations.ports import MetricsPort

#: Matches `BackgroundJob.resource_key`'s persisted `max_length` - every
#: resource key built here must fit, not just the Live Research one.
_MAX_RESOURCE_KEY_LENGTH = 300

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
    "live_research_job_resource_key",
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


def live_research_job_resource_key(context: JobExecutionContext) -> str:
    """Phase G2B: locks `LIVE_RESEARCH_RUN_EXECUTION` per requester, so a
    manual re-trigger cannot race a job-level retry for the same logical
    request. Built entirely from `JobExecutionContext` - never a
    `request_id` (the domain `ResearchRequest` does not exist yet when
    this runs, at job-creation time), never the raw idempotency key
    (only a bounded SHA-256 hash of it), never the research question,
    and never a provider secret.

    Uses the same `account:{id}` / `integration:{id}` requester-identity
    convention as `BackgroundJobORM.requester_key` and
    `domain.live_research.hashing.requester_key`; falls back to a
    deterministic `source:{trigger_source}` key (rather than raising)
    when neither identity field is set - e.g. an `ADMIN_CLI`/`SYSTEM`-
    triggered job with no attached requester, a real, reachable state
    during Stage 0/1 rollout.
    """
    if context.requested_by_account_id is not None:
        requester = f"account:{context.requested_by_account_id}"
    elif context.requested_by_integration_id is not None:
        requester = f"integration:{context.requested_by_integration_id}"
    else:
        requester = f"source:{context.trigger_source.value}"

    idempotency_hash = hashlib.sha256(context.idempotency_key.encode("utf-8")).hexdigest()[:32]
    key = f"live-research-job:{requester}:{idempotency_hash}"
    assert len(key) <= _MAX_RESOURCE_KEY_LENGTH, "live_research_job_resource_key exceeded the persisted bound"
    return key


def reconcile_waiting_coach_runs_resource_key() -> str:
    """Spec G2D2 section 13: a single fixed key so at most one
    reconciliation sweep runs at a time - overlapping sweeps would
    otherwise race on the same idempotency-key read-then-write the
    terminal-transaction hook (`_maybe_create_coach_resume_job`) uses."""
    return "reconcile-waiting-coach-runs"


def coach_research_resume_resource_key(*, coach_run_id: UUID) -> str:
    """Locks `COACH_RESEARCH_RESUME` per Coach run (spec G2D2 section 12),
    so the terminal-transaction hook and the reconciliation sweep can
    never both resume the same run concurrently - the same thread-safety
    guarantee `learning_orchestrator_thread_resource_key` gives the Coach
    graph itself, but keyed on the durable run id rather than the
    in-process Redis thread lock."""
    return f"coach-research-resume:{coach_run_id}"


def expire_stale_waiting_for_research_resource_key() -> str:
    """G2D2/H1 correction pass, section 9: a single fixed key, distinct
    from `reconcile_waiting_coach_runs_resource_key`, so the deadline-
    expiry sweep and the resume-recovery sweep can each run
    independently without contending on the same lock."""
    return "expire-stale-waiting-for-research"


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
