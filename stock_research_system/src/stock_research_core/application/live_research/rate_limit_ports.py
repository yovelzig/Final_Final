"""Per-account abuse limits for the automatic learner Live Research
trigger (spec G2D2 section 18) - a distinct concern from the existing
IP-keyed `application.identity.ports.RateLimiterPort`, which has no
notion of a trusted account identity or of "how many research jobs is
this account allowed to have outstanding at once."
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    #: Which bound was hit, if any - `None` when `allowed` is True.
    #: Never exposed to the learner verbatim (the caller maps this to a
    #: bounded localized message), only logged/used internally.
    reason: str | None = None


class AccountResearchRateLimiterPort(Protocol):
    """Checked by `request_live_research` before `BackgroundJobService.
    create_job` - never after. A denied decision creates no job, no
    `ResearchRequest`, and exposes no internal counters to the learner.

    G2D2/H1 correction pass, section 8: the per-account *concurrency*
    slot (as opposed to the separate, cumulative hourly-usage counter) is
    an atomic acquire/release contract, not a bare TTL-only counter -
    `reservation_id` is a stable identity known to the caller *before*
    the corresponding `BackgroundJob` exists (`request_live_research`
    uses the Coach run's own `run_id`), and is what `release` uses to
    give back exactly the slot `try_acquire` reserved. A rejected
    `try_acquire` never reserves a slot at all, so it never needs (and
    must never receive) a matching `release` call.
    """

    async def try_acquire(self, *, account_id: UUID, reservation_id: str) -> RateLimitDecision: ...

    async def release(self, *, account_id: UUID, reservation_id: str) -> None:
        """Idempotent: releasing a reservation that was never acquired,
        or was already released, is a safe no-op - never an error. Never
        touches the separate, cumulative hourly-usage counter."""
        ...
