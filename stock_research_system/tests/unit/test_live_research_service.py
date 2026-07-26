"""Unit tests for `ResearchRequestService`.

Uses simple in-memory fake repositories (no SQLAlchemy, no PostgreSQL) so
these tests exercise the service's own logic - idempotency, attempt
allocation, state transitions, deduplication, and claim/evidence-link
enforcement - without any I/O.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

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
from stock_research_core.application.live_research.service import ResearchRequestService
from stock_research_core.domain.live_research.enums import (
    ClaimCategory,
    ClaimStatus,
    EvidenceClassification,
    EvidenceStance,
    FailureCategory,
    ResearchRunStatus,
    ResearchScope,
    SourceType,
)
from stock_research_core.domain.live_research.models import (
    ClaimEvidenceLink,
    EvidenceItem,
    ResearchClaim,
    ResearchRequest,
    ResearchRun,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeResearchRequestRepository:
    def __init__(self) -> None:
        self.by_id: dict[UUID, ResearchRequest] = {}

    async def create(self, request: ResearchRequest) -> ResearchRequest:
        self.by_id[request.request_id] = request
        return request

    async def get(self, request_id: UUID) -> ResearchRequest | None:
        return self.by_id.get(request_id)

    async def get_for_update(self, request_id: UUID) -> ResearchRequest | None:
        return self.by_id.get(request_id)

    async def get_by_idempotency_key(self, *, requester_key: str, idempotency_key: str):
        for request in self.by_id.values():
            from stock_research_core.domain.live_research.hashing import requester_key as derive

            key = derive(
                account_id=request.requested_by_account_id,
                integration_id=request.requested_by_integration_id,
            )
            if key == requester_key and request.idempotency_key == idempotency_key:
                return request
        return None


class _FakeResearchRunRepository:
    def __init__(self) -> None:
        self.by_id: dict[UUID, ResearchRun] = {}

    async def create(self, run: ResearchRun) -> ResearchRun:
        self.by_id[run.run_id] = run
        return run

    async def get(self, run_id: UUID, *, for_update: bool = False) -> ResearchRun | None:
        return self.by_id.get(run_id)

    async def get_active_run_for_request(self, request_id: UUID) -> ResearchRun | None:
        for run in self.by_id.values():
            if run.request_id == request_id and run.status in (
                ResearchRunStatus.QUEUED, ResearchRunStatus.RUNNING,
            ):
                return run
        return None

    async def get_max_attempt_number(self, request_id: UUID) -> int:
        attempts = [run.attempt_number for run in self.by_id.values() if run.request_id == request_id]
        return max(attempts) if attempts else 0

    async def list_for_request(self, request_id: UUID) -> list[ResearchRun]:
        return sorted(
            (run for run in self.by_id.values() if run.request_id == request_id),
            key=lambda run: run.attempt_number,
        )

    async def mark_running(self, run_id: UUID, *, started_at: datetime) -> ResearchRun:
        updated = self.by_id[run_id].model_copy(update={"status": ResearchRunStatus.RUNNING, "started_at": started_at})
        self.by_id[run_id] = updated
        return updated

    async def mark_completed(self, run_id: UUID, *, completed_at: datetime) -> ResearchRun:
        updated = self.by_id[run_id].model_copy(
            update={"status": ResearchRunStatus.COMPLETED, "completed_at": completed_at}
        )
        self.by_id[run_id] = updated
        return updated

    async def mark_failed(
        self, run_id: UUID, *, completed_at: datetime, failure_category, failure_message: str, retryable: bool
    ) -> ResearchRun:
        updated = self.by_id[run_id].model_copy(
            update={
                "status": ResearchRunStatus.FAILED,
                "completed_at": completed_at,
                "failure_category": failure_category,
                "failure_message": failure_message,
                "retryable": retryable,
            }
        )
        self.by_id[run_id] = updated
        return updated

    async def mark_cancelled(self, run_id: UUID, *, cancelled_at: datetime) -> ResearchRun:
        updated = self.by_id[run_id].model_copy(
            update={"status": ResearchRunStatus.CANCELLED, "cancelled_at": cancelled_at, "completed_at": cancelled_at}
        )
        self.by_id[run_id] = updated
        return updated


class _FakeEvidenceItemRepository:
    def __init__(self) -> None:
        self.by_id: dict[UUID, EvidenceItem] = {}

    async def create(self, item: EvidenceItem) -> EvidenceItem:
        self.by_id[item.evidence_id] = item
        return item

    async def get(self, evidence_id: UUID) -> EvidenceItem | None:
        return self.by_id.get(evidence_id)

    async def get_by_content_hash(self, run_id: UUID, content_hash: str) -> EvidenceItem | None:
        for item in self.by_id.values():
            if item.run_id == run_id and item.content_hash == content_hash:
                return item
        return None

    async def list_for_run(self, run_id: UUID) -> list[EvidenceItem]:
        return [item for item in self.by_id.values() if item.run_id == run_id]


class _FakeResearchClaimRepository:
    def __init__(self) -> None:
        self.by_id: dict[UUID, ResearchClaim] = {}

    async def create(self, claim: ResearchClaim) -> ResearchClaim:
        self.by_id[claim.claim_id] = claim
        return claim

    async def get(self, claim_id: UUID) -> ResearchClaim | None:
        return self.by_id.get(claim_id)

    async def list_for_run(self, run_id: UUID) -> list[ResearchClaim]:
        return [claim for claim in self.by_id.values() if claim.run_id == run_id]

    async def update_status(self, claim_id: UUID, status: ClaimStatus, *, confidence_score: float | None = None):
        updated = self.by_id[claim_id].model_copy(update={"status": status, "confidence_score": confidence_score})
        self.by_id[claim_id] = updated
        return updated


class _FakeClaimEvidenceLinkRepository:
    def __init__(self) -> None:
        self.links: list[ClaimEvidenceLink] = []

    async def create_link(self, claim_id: UUID, evidence_id: UUID, stance: EvidenceStance) -> ClaimEvidenceLink:
        link = ClaimEvidenceLink(claim_id=claim_id, evidence_id=evidence_id, stance=stance)
        self.links.append(link)
        return link

    async def get_link(self, claim_id: UUID, evidence_id: UUID) -> ClaimEvidenceLink | None:
        for link in self.links:
            if link.claim_id == claim_id and link.evidence_id == evidence_id:
                return link
        return None

    async def list_links_for_claim(self, claim_id: UUID) -> list[ClaimEvidenceLink]:
        return [link for link in self.links if link.claim_id == claim_id]

    async def list_links_for_evidence(self, evidence_id: UUID) -> list[ClaimEvidenceLink]:
        return [link for link in self.links if link.evidence_id == evidence_id]


class _FakeUnitOfWork:
    def __init__(self) -> None:
        self.research_requests = _FakeResearchRequestRepository()
        self.research_runs = _FakeResearchRunRepository()
        self.evidence_items = _FakeEvidenceItemRepository()
        self.research_claims = _FakeResearchClaimRepository()
        self.claim_evidence_links = _FakeClaimEvidenceLinkRepository()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


@pytest.fixture
def uow() -> _FakeUnitOfWork:
    return _FakeUnitOfWork()


@pytest.fixture
def service(uow: _FakeUnitOfWork) -> ResearchRequestService:
    return ResearchRequestService(unit_of_work_factory=lambda: uow, clock=lambda: NOW)


# ---------------------------------------------------------------------------
# submit_request: idempotency
# ---------------------------------------------------------------------------


async def test_submit_request_creates_a_new_request(service: ResearchRequestService) -> None:
    result = await service.submit_request(
        account_id=uuid4(), original_question="What is AAPL's revenue?",
        scope=ResearchScope.COMPANY_OVERVIEW, subject_security_id=uuid4(), idempotency_key="key-1",
    )
    assert result.created is True
    assert result.request.normalized_query == "what is aapl's revenue?"


async def test_submit_request_is_idempotent_for_same_identity(service: ResearchRequestService) -> None:
    account_id = uuid4()
    security_id = uuid4()
    first = await service.submit_request(
        account_id=account_id, original_question="What is AAPL's revenue?",
        scope=ResearchScope.COMPANY_OVERVIEW, subject_security_id=security_id, idempotency_key="key-1",
    )
    second = await service.submit_request(
        account_id=account_id, original_question="What is AAPL's revenue?",
        scope=ResearchScope.COMPANY_OVERVIEW, subject_security_id=security_id, idempotency_key="key-1",
    )
    assert second.created is False
    assert second.request.request_id == first.request.request_id


async def test_submit_request_conflicts_on_reused_key_with_different_identity(
    service: ResearchRequestService,
) -> None:
    account_id = uuid4()
    await service.submit_request(
        account_id=account_id, original_question="What is AAPL's revenue?",
        scope=ResearchScope.COMPANY_OVERVIEW, subject_security_id=uuid4(), idempotency_key="key-1",
    )
    with pytest.raises(ResearchRequestConflictError):
        await service.submit_request(
            account_id=account_id, original_question="What is AAPL's guidance?",
            scope=ResearchScope.COMPANY_OVERVIEW, subject_security_id=uuid4(), idempotency_key="key-1",
        )


# ---------------------------------------------------------------------------
# create_next_run: attempt numbering, never reactivates FAILED
# ---------------------------------------------------------------------------


async def test_create_next_run_starts_at_one(service: ResearchRequestService) -> None:
    submission = await service.submit_request(
        account_id=uuid4(), original_question="Question?", scope=ResearchScope.GENERAL_QUESTION,
        idempotency_key="key-1",
    )
    run = await service.create_next_run(submission.request.request_id)
    assert run.attempt_number == 1
    assert run.status == ResearchRunStatus.QUEUED


async def test_create_next_run_rejects_when_an_active_run_exists(service: ResearchRequestService) -> None:
    submission = await service.submit_request(
        account_id=uuid4(), original_question="Question?", scope=ResearchScope.GENERAL_QUESTION,
        idempotency_key="key-1",
    )
    await service.create_next_run(submission.request.request_id)
    with pytest.raises(InvalidResearchRunStateError):
        await service.create_next_run(submission.request.request_id)


async def test_create_next_run_after_failure_increments_attempt_number_as_a_new_row(
    service: ResearchRequestService,
) -> None:
    submission = await service.submit_request(
        account_id=uuid4(), original_question="Question?", scope=ResearchScope.GENERAL_QUESTION,
        idempotency_key="key-1",
    )
    first_run = await service.create_next_run(submission.request.request_id)
    await service.start_run(first_run.run_id)
    failed = await service.fail_run(
        first_run.run_id, failure_category=FailureCategory.PROVIDER_ERROR,
        message="The provider timed out.", retryable=True,
    )
    assert failed.status == ResearchRunStatus.FAILED

    second_run = await service.create_next_run(submission.request.request_id)
    assert second_run.attempt_number == 2
    assert second_run.run_id != first_run.run_id
    # the original row is untouched - never reactivated
    assert failed.status == ResearchRunStatus.FAILED


async def test_create_next_run_raises_when_request_missing(service: ResearchRequestService) -> None:
    with pytest.raises(ResearchRequestNotFoundError):
        await service.create_next_run(uuid4())


# ---------------------------------------------------------------------------
# run lifecycle: idempotent no-ops, illegal transitions
# ---------------------------------------------------------------------------


async def test_start_run_is_idempotent_when_already_running(service: ResearchRequestService) -> None:
    submission = await service.submit_request(
        account_id=uuid4(), original_question="Question?", scope=ResearchScope.GENERAL_QUESTION,
        idempotency_key="key-1",
    )
    run = await service.create_next_run(submission.request.request_id)
    started_once = await service.start_run(run.run_id)
    started_twice = await service.start_run(run.run_id)
    assert started_once.status == started_twice.status == ResearchRunStatus.RUNNING


async def test_start_run_is_idempotent_when_already_terminal(service: ResearchRequestService) -> None:
    submission = await service.submit_request(
        account_id=uuid4(), original_question="Question?", scope=ResearchScope.GENERAL_QUESTION,
        idempotency_key="key-1",
    )
    run = await service.create_next_run(submission.request.request_id)
    await service.start_run(run.run_id)
    completed = await service.complete_run(run.run_id)
    assert completed.status == ResearchRunStatus.COMPLETED
    # duplicate delivery after terminal is a no-op, not an error
    result = await service.start_run(run.run_id)
    assert result.status == ResearchRunStatus.COMPLETED


async def test_complete_run_rejects_a_run_that_never_started(service: ResearchRequestService) -> None:
    submission = await service.submit_request(
        account_id=uuid4(), original_question="Question?", scope=ResearchScope.GENERAL_QUESTION,
        idempotency_key="key-1",
    )
    run = await service.create_next_run(submission.request.request_id)
    with pytest.raises(InvalidResearchRunStateError):
        await service.complete_run(run.run_id)


async def test_run_lifecycle_methods_raise_not_found_for_unknown_run(service: ResearchRequestService) -> None:
    with pytest.raises(ResearchRunNotFoundError):
        await service.start_run(uuid4())


# ---------------------------------------------------------------------------
# evidence deduplication
# ---------------------------------------------------------------------------


def _evidence_kwargs(**overrides: object) -> dict:
    defaults: dict = dict(
        source_type=SourceType.SEC_OFFICIAL_FILING, classification=EvidenceClassification.OFFICIAL,
        source_url="https://www.sec.gov/example", official_identifier="0001234567-26-000001",
        source_title="Form 10-K", publisher="SEC", published_at=NOW,
        raw_excerpt="Revenue increased.", normalized_text="revenue increased",
    )
    defaults.update(overrides)
    return defaults


async def test_record_evidence_rejects_duplicate_content_hash_within_a_run(
    service: ResearchRequestService,
) -> None:
    run_id = uuid4()
    await service.record_evidence(run_id, **_evidence_kwargs())
    with pytest.raises(DuplicateEvidenceError):
        await service.record_evidence(run_id, **_evidence_kwargs())


async def test_record_evidence_allows_the_same_content_in_a_different_run(
    service: ResearchRequestService,
) -> None:
    first = await service.record_evidence(uuid4(), **_evidence_kwargs())
    second = await service.record_evidence(uuid4(), **_evidence_kwargs())
    assert first.content_hash == second.content_hash
    assert first.evidence_id != second.evidence_id


# ---------------------------------------------------------------------------
# claim-evidence links + claim status enforcement
# ---------------------------------------------------------------------------


async def test_link_evidence_to_claim_rejects_duplicate_pair(service: ResearchRequestService) -> None:
    claim_id = uuid4()
    evidence_id = uuid4()
    await service.link_evidence_to_claim(claim_id, evidence_id, EvidenceStance.SUPPORTS)
    with pytest.raises(DuplicateClaimEvidenceLinkError):
        await service.link_evidence_to_claim(claim_id, evidence_id, EvidenceStance.CONTRADICTS)


async def test_update_claim_status_refuses_corroborated_without_supports_link(
    service: ResearchRequestService,
) -> None:
    claim = await service.record_claim(uuid4(), claim_text="Revenue grew.", category=ClaimCategory.FINANCIAL_METRIC)
    with pytest.raises(InvalidClaimStatusTransitionError):
        await service.update_claim_status(claim.claim_id, ClaimStatus.CORROBORATED)


async def test_update_claim_status_allows_corroborated_with_supports_link(
    service: ResearchRequestService,
) -> None:
    claim = await service.record_claim(uuid4(), claim_text="Revenue grew.", category=ClaimCategory.FINANCIAL_METRIC)
    await service.link_evidence_to_claim(claim.claim_id, uuid4(), EvidenceStance.SUPPORTS)
    updated = await service.update_claim_status(claim.claim_id, ClaimStatus.CORROBORATED, confidence_score=0.9)
    assert updated.status == ClaimStatus.CORROBORATED


async def test_update_claim_status_refuses_unresolved_conflict_without_both_stances(
    service: ResearchRequestService,
) -> None:
    claim = await service.record_claim(uuid4(), claim_text="Revenue grew.", category=ClaimCategory.FINANCIAL_METRIC)
    await service.link_evidence_to_claim(claim.claim_id, uuid4(), EvidenceStance.SUPPORTS)
    with pytest.raises(InvalidClaimStatusTransitionError):
        await service.update_claim_status(claim.claim_id, ClaimStatus.UNRESOLVED_CONFLICT)


async def test_update_claim_status_allows_unresolved_conflict_with_both_stances(
    service: ResearchRequestService,
) -> None:
    claim = await service.record_claim(uuid4(), claim_text="Revenue grew.", category=ClaimCategory.FINANCIAL_METRIC)
    await service.link_evidence_to_claim(claim.claim_id, uuid4(), EvidenceStance.SUPPORTS)
    await service.link_evidence_to_claim(claim.claim_id, uuid4(), EvidenceStance.CONTRADICTS)
    updated = await service.update_claim_status(claim.claim_id, ClaimStatus.UNRESOLVED_CONFLICT)
    assert updated.status == ClaimStatus.UNRESOLVED_CONFLICT


async def test_update_claim_status_raises_not_found_for_unknown_claim(service: ResearchRequestService) -> None:
    with pytest.raises(ResearchClaimNotFoundError):
        await service.update_claim_status(uuid4(), ClaimStatus.CORROBORATED)
