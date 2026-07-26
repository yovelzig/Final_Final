"""Application service for the provider-neutral Live Research domain
(Phase G1).

`ResearchRequestService` only manipulates domain objects and persists
them via an injected `UnitOfWorkPort` factory - it never makes a
provider call, an HTTP fetch, or a job-queue enqueue. A later phase
(G2) adds a `BackgroundJobType`/`JobHandlerPort` implementation that
calls into this service; none of that orchestration lives here.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from stock_research_core.application.exceptions import (
    DuplicateClaimEvidenceLinkError,
    DuplicateEvidenceError,
    InvalidClaimStatusTransitionError,
    InvalidResearchRunStateError,
    ResearchClaimNotFoundError,
    ResearchRequestConflictError,
    ResearchRequestNotFoundError,
    ResearchRunNotFoundError,
)
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.domain.live_research.enums import (
    TERMINAL_RESEARCH_RUN_STATUSES,
    ClaimCategory,
    ClaimStatus,
    EvidenceClassification,
    EvidenceStance,
    FailureCategory,
    ResearchRunStatus,
    ResearchScope,
    SourceType,
)
from stock_research_core.domain.live_research.hashing import (
    compute_evidence_content_hash,
    compute_request_hash,
    normalize_query,
)
from stock_research_core.domain.live_research.hashing import requester_key as _derive_requester_key
from stock_research_core.domain.live_research.models import (
    ClaimEvidenceLink,
    EvidenceItem,
    ResearchClaim,
    ResearchRequest,
    ResearchRun,
)
from stock_research_core.domain.models import DomainModel, utc_now

Clock = Callable[[], datetime]


class RequestSubmissionResult(DomainModel):
    request: ResearchRequest
    created: bool


class ResearchRequestService:
    """Creates and progresses `ResearchRequest`/`ResearchRun` records and
    their evidence/claims. Constructed once per process from an injected
    Unit-of-Work factory, exactly like every other FinQuest application
    service (e.g. `BackgroundJobService`)."""

    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWorkPort], clock: Clock = utc_now) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock

    # -- request submission -----------------------------------------------

    async def submit_request(
        self,
        *,
        account_id: UUID | None = None,
        integration_id: UUID | None = None,
        original_question: str,
        scope: ResearchScope,
        subject_security_id: UUID | None = None,
        subject_raw_text: str | None = None,
        idempotency_key: str,
    ) -> RequestSubmissionResult:
        """Idempotent create: the same requester + idempotency key with the
        same derived request identity returns the existing request; the
        same key with a *different* identity raises
        `ResearchRequestConflictError` rather than silently returning an
        unrelated request."""
        requester = _derive_requester_key(account_id=account_id, integration_id=integration_id)
        normalized_query = normalize_query(original_question)
        request_hash = compute_request_hash(
            normalized_query=normalized_query,
            scope=scope.value,
            subject_security_id=subject_security_id,
            subject_raw_text=subject_raw_text,
        )

        async with self._unit_of_work_factory() as uow:
            existing = await uow.research_requests.get_by_idempotency_key(
                requester_key=requester, idempotency_key=idempotency_key
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ResearchRequestConflictError(
                        f"Idempotency key '{idempotency_key}' was already used with a different "
                        "research request (question, scope, or subject changed)."
                    )
                return RequestSubmissionResult(request=existing, created=False)

            request = ResearchRequest(
                requested_by_account_id=account_id,
                requested_by_integration_id=integration_id,
                original_question=original_question,
                normalized_query=normalized_query,
                subject_security_id=subject_security_id,
                subject_raw_text=subject_raw_text,
                scope=scope,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            created = await uow.research_requests.create(request)
            await uow.commit()

        return RequestSubmissionResult(request=created, created=True)

    # -- run lifecycle -----------------------------------------------

    async def create_next_run(self, request_id: UUID) -> ResearchRun:
        """Always creates a *new* `ResearchRun` row with the next
        `attempt_number` - never reactivates or modifies a FAILED run.

        Concurrency-safe: locks the parent `ResearchRequest` row with
        `SELECT ... FOR UPDATE` for the duration of this transaction, so
        two concurrent callers computing `max(attempt_number) + 1` for the
        same request cannot race - the second caller blocks on the lock
        until the first commits, then reads the freshly-committed max.
        """
        async with self._unit_of_work_factory() as uow:
            request = await uow.research_requests.get_for_update(request_id)
            if request is None:
                raise ResearchRequestNotFoundError(f"No research request found with id '{request_id}'.")

            active = await uow.research_runs.get_active_run_for_request(request_id)
            if active is not None:
                raise InvalidResearchRunStateError(
                    f"Research request '{request_id}' already has a non-terminal run '{active.run_id}' "
                    f"(status {active.status.value})."
                )

            next_attempt_number = await uow.research_runs.get_max_attempt_number(request_id) + 1
            run = ResearchRun(request_id=request_id, attempt_number=next_attempt_number)
            created = await uow.research_runs.create(run)
            await uow.commit()

        return created

    async def start_run(self, run_id: UUID) -> ResearchRun:
        started_at = self._clock()
        async with self._unit_of_work_factory() as uow:
            run = await uow.research_runs.get(run_id, for_update=True)
            if run is None:
                raise ResearchRunNotFoundError(f"No research run found with id '{run_id}'.")

            if run.status == ResearchRunStatus.RUNNING or run.status in TERMINAL_RESEARCH_RUN_STATUSES:
                await uow.commit()
                return run  # idempotent no-op: duplicate start signal, not a state reversal

            if run.status != ResearchRunStatus.QUEUED:
                await uow.commit()
                raise InvalidResearchRunStateError(
                    f"Run '{run_id}' is in status {run.status.value} and cannot be started."
                )

            updated = await uow.research_runs.mark_running(run_id, started_at=started_at)
            await uow.commit()

        return updated

    async def complete_run(self, run_id: UUID) -> ResearchRun:
        completed_at = self._clock()
        async with self._unit_of_work_factory() as uow:
            run = await uow.research_runs.get(run_id, for_update=True)
            if run is None:
                raise ResearchRunNotFoundError(f"No research run found with id '{run_id}'.")

            if run.status in TERMINAL_RESEARCH_RUN_STATUSES:
                await uow.commit()
                return run  # idempotent no-op: terminal rows never transition again

            if run.status != ResearchRunStatus.RUNNING:
                await uow.commit()
                raise InvalidResearchRunStateError(
                    f"Run '{run_id}' is in status {run.status.value} and cannot be completed."
                )

            updated = await uow.research_runs.mark_completed(run_id, completed_at=completed_at)
            await uow.commit()

        return updated

    async def fail_run(
        self, run_id: UUID, *, failure_category: FailureCategory, message: str, retryable: bool
    ) -> ResearchRun:
        completed_at = self._clock()
        async with self._unit_of_work_factory() as uow:
            run = await uow.research_runs.get(run_id, for_update=True)
            if run is None:
                raise ResearchRunNotFoundError(f"No research run found with id '{run_id}'.")

            if run.status in TERMINAL_RESEARCH_RUN_STATUSES:
                await uow.commit()
                return run  # idempotent no-op: terminal rows never transition again

            if run.status not in (ResearchRunStatus.QUEUED, ResearchRunStatus.RUNNING):
                await uow.commit()
                raise InvalidResearchRunStateError(
                    f"Run '{run_id}' is in status {run.status.value} and cannot be failed."
                )

            updated = await uow.research_runs.mark_failed(
                run_id,
                completed_at=completed_at,
                failure_category=failure_category,
                failure_message=message,
                retryable=retryable,
            )
            await uow.commit()

        return updated

    async def cancel_run(self, run_id: UUID) -> ResearchRun:
        cancelled_at = self._clock()
        async with self._unit_of_work_factory() as uow:
            run = await uow.research_runs.get(run_id, for_update=True)
            if run is None:
                raise ResearchRunNotFoundError(f"No research run found with id '{run_id}'.")

            if run.status in TERMINAL_RESEARCH_RUN_STATUSES:
                await uow.commit()
                return run  # idempotent no-op: terminal rows never transition again

            updated = await uow.research_runs.mark_cancelled(run_id, cancelled_at=cancelled_at)
            await uow.commit()

        return updated

    # -- evidence -----------------------------------------------

    async def record_evidence(
        self,
        run_id: UUID,
        *,
        source_type: SourceType,
        classification: EvidenceClassification,
        source_title: str,
        publisher: str,
        source_url: str | None = None,
        official_identifier: str | None = None,
        published_at: datetime | None = None,
        raw_excerpt: str | None = None,
        normalized_text: str | None = None,
        structured_facts: dict[str, Any] | None = None,
    ) -> EvidenceItem:
        content_hash = compute_evidence_content_hash(
            source_type=source_type.value,
            classification=classification.value,
            source_url=source_url,
            official_identifier=official_identifier,
            source_title=source_title,
            publisher=publisher,
            published_at=published_at,
            raw_excerpt=raw_excerpt,
            normalized_text=normalized_text,
            structured_facts=structured_facts,
        )
        evidence = EvidenceItem(
            run_id=run_id,
            source_type=source_type,
            classification=classification,
            source_url=source_url,
            official_identifier=official_identifier,
            source_title=source_title,
            publisher=publisher,
            published_at=published_at,
            raw_excerpt=raw_excerpt,
            normalized_text=normalized_text,
            structured_facts=structured_facts,
            content_hash=content_hash,
        )

        async with self._unit_of_work_factory() as uow:
            existing = await uow.evidence_items.get_by_content_hash(run_id, content_hash)
            if existing is not None:
                raise DuplicateEvidenceError(
                    f"Run '{run_id}' already has an evidence item with content_hash '{content_hash}'."
                )
            created = await uow.evidence_items.create(evidence)
            await uow.commit()

        return created

    # -- claims -----------------------------------------------

    async def record_claim(self, run_id: UUID, *, claim_text: str, category: ClaimCategory) -> ResearchClaim:
        claim = ResearchClaim(run_id=run_id, claim_text=claim_text, category=category)
        async with self._unit_of_work_factory() as uow:
            created = await uow.research_claims.create(claim)
            await uow.commit()
        return created

    async def link_evidence_to_claim(
        self, claim_id: UUID, evidence_id: UUID, stance: EvidenceStance
    ) -> ClaimEvidenceLink:
        async with self._unit_of_work_factory() as uow:
            existing = await uow.claim_evidence_links.get_link(claim_id, evidence_id)
            if existing is not None:
                raise DuplicateClaimEvidenceLinkError(
                    f"Claim '{claim_id}' and evidence '{evidence_id}' are already linked."
                )
            created = await uow.claim_evidence_links.create_link(claim_id, evidence_id, stance)
            await uow.commit()
        return created

    async def update_claim_status(
        self, claim_id: UUID, status: ClaimStatus, *, confidence_score: float | None = None
    ) -> ResearchClaim:
        """Enforces the evidence-link preconditions that `ResearchClaim`
        itself cannot validate (it has no visibility into sibling
        `ClaimEvidenceLink` rows): CORROBORATED requires at least one
        SUPPORTS link; UNRESOLVED_CONFLICT requires at least one SUPPORTS
        link *and* at least one CONTRADICTS link. G1 never computes or
        assigns these statuses automatically - this method only validates
        a status change that was explicitly requested."""
        async with self._unit_of_work_factory() as uow:
            claim = await uow.research_claims.get(claim_id)
            if claim is None:
                raise ResearchClaimNotFoundError(f"No research claim found with id '{claim_id}'.")

            links = await uow.claim_evidence_links.list_links_for_claim(claim_id)
            stances = {link.stance for link in links}

            if status == ClaimStatus.CORROBORATED and EvidenceStance.SUPPORTS not in stances:
                raise InvalidClaimStatusTransitionError(
                    f"Claim '{claim_id}' cannot be marked CORROBORATED without at least one SUPPORTS link."
                )
            if status == ClaimStatus.UNRESOLVED_CONFLICT and not (
                EvidenceStance.SUPPORTS in stances and EvidenceStance.CONTRADICTS in stances
            ):
                raise InvalidClaimStatusTransitionError(
                    f"Claim '{claim_id}' cannot be marked UNRESOLVED_CONFLICT without both a SUPPORTS "
                    "and a CONTRADICTS link."
                )

            updated = await uow.research_claims.update_status(claim_id, status, confidence_score=confidence_score)
            await uow.commit()

        return updated
