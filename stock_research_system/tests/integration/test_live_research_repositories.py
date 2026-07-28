"""PostgreSQL integration tests: the Live Research domain repositories
(Phase G1) - `ResearchRequestRepository`, `ResearchRunRepository`,
`EvidenceItemRepository`, `ResearchClaimRepository`,
`ClaimEvidenceLinkRepository`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import (
    DuplicateClaimEvidenceLinkError,
    PersistenceError,
)
from stock_research_core.domain.live_research.enums import (
    ClaimCategory,
    EvidenceClassification,
    EvidenceStance,
    FailureCategory,
    ResearchRunStatus,
    ResearchScope,
    SourceType,
)
from stock_research_core.domain.live_research.hashing import compute_evidence_content_hash
from stock_research_core.domain.live_research.models import (
    EvidenceItem,
    ResearchClaim,
    ResearchRequest,
    ResearchRun,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _request(**overrides: object) -> ResearchRequest:
    defaults: dict = dict(
        requested_by_account_id=uuid4(),
        original_question="What is going on with this company?",
        normalized_query="what is going on with this company?",
        scope=ResearchScope.GENERAL_QUESTION,
        idempotency_key=f"key-{uuid4().hex[:8]}",
        request_hash="a" * 64,
    )
    defaults.update(overrides)
    return ResearchRequest(**defaults)


async def _create_request(uow_factory, **overrides: object) -> ResearchRequest:
    request = _request(**overrides)
    async with uow_factory() as uow:
        created = await uow.research_requests.create(request)
        await uow.commit()
    return created


async def _create_run(uow_factory, request_id, *, attempt_number: int = 1) -> ResearchRun:
    run = ResearchRun(request_id=request_id, attempt_number=attempt_number)
    async with uow_factory() as uow:
        created = await uow.research_runs.create(run)
        await uow.commit()
    return created


def _evidence_kwargs(**overrides: object) -> dict:
    defaults: dict = dict(
        source_type=SourceType.SEC_OFFICIAL_FILING, classification=EvidenceClassification.OFFICIAL,
        source_url="https://www.sec.gov/example", official_identifier="0001234567-26-000001",
        source_title="Form 10-K", publisher="SEC", published_at=NOW,
        raw_excerpt="Revenue increased.", normalized_text="revenue increased", structured_facts=None,
    )
    defaults.update(overrides)
    return defaults


async def _create_evidence(uow_factory, run_id, **overrides: object) -> EvidenceItem:
    kwargs = _evidence_kwargs(**overrides)
    content_hash = compute_evidence_content_hash(
        source_type=kwargs["source_type"].value, classification=kwargs["classification"].value,
        source_url=kwargs["source_url"], official_identifier=kwargs["official_identifier"],
        source_title=kwargs["source_title"], publisher=kwargs["publisher"], published_at=kwargs["published_at"],
        raw_excerpt=kwargs["raw_excerpt"], normalized_text=kwargs["normalized_text"],
        structured_facts=kwargs["structured_facts"],
    )
    item = EvidenceItem(run_id=run_id, content_hash=content_hash, **kwargs)
    async with uow_factory() as uow:
        created = await uow.evidence_items.create(item)
        await uow.commit()
    return created


async def _create_claim(uow_factory, run_id, **overrides: object) -> ResearchClaim:
    defaults: dict = dict(claim_text="Revenue grew 10% year over year.", category=ClaimCategory.FINANCIAL_METRIC)
    defaults.update(overrides)
    claim = ResearchClaim(run_id=run_id, **defaults)
    async with uow_factory() as uow:
        created = await uow.research_claims.create(claim)
        await uow.commit()
    return created


# ---------------------------------------------------------------------------
# ResearchRequest
# ---------------------------------------------------------------------------


async def test_research_request_round_trips(uow_factory) -> None:
    created = await _create_request(uow_factory)
    async with uow_factory() as uow:
        fetched = await uow.research_requests.get(created.request_id)
    assert fetched is not None
    assert fetched.request_id == created.request_id
    assert fetched.original_question == created.original_question


async def test_research_request_get_returns_none_when_missing(uow_factory) -> None:
    async with uow_factory() as uow:
        result = await uow.research_requests.get(uuid4())
    assert result is None


async def test_research_request_get_by_idempotency_key(uow_factory) -> None:
    idempotency_key = f"key-{uuid4().hex[:8]}"
    created = await _create_request(uow_factory, idempotency_key=idempotency_key)
    async with uow_factory() as uow:
        found = await uow.research_requests.get_by_idempotency_key(
            requester_key=f"account:{created.requested_by_account_id}", idempotency_key=idempotency_key
        )
    assert found is not None
    assert found.request_id == created.request_id


async def test_research_request_idempotency_scope_is_unique(uow_factory) -> None:
    account_id = uuid4()
    idempotency_key = f"key-{uuid4().hex[:8]}"
    await _create_request(uow_factory, requested_by_account_id=account_id, idempotency_key=idempotency_key)
    with pytest.raises(PersistenceError):
        await _create_request(uow_factory, requested_by_account_id=account_id, idempotency_key=idempotency_key)


async def test_research_request_get_for_update_lock(uow_factory) -> None:
    created = await _create_request(uow_factory)
    async with uow_factory() as uow:
        locked = await uow.research_requests.get_for_update(created.request_id)
        await uow.commit()
    assert locked is not None
    assert locked.request_id == created.request_id


# ---------------------------------------------------------------------------
# ResearchRun
# ---------------------------------------------------------------------------


async def test_research_run_round_trips(uow_factory) -> None:
    request = await _create_request(uow_factory)
    created = await _create_run(uow_factory, request.request_id)
    async with uow_factory() as uow:
        fetched = await uow.research_runs.get(created.run_id)
    assert fetched is not None
    assert fetched.attempt_number == 1
    assert fetched.status == ResearchRunStatus.QUEUED


async def test_research_run_request_attempt_number_is_unique(uow_factory) -> None:
    request = await _create_request(uow_factory)
    await _create_run(uow_factory, request.request_id, attempt_number=1)
    with pytest.raises(PersistenceError):
        await _create_run(uow_factory, request.request_id, attempt_number=1)


async def test_research_run_only_one_active_run_per_request(uow_factory) -> None:
    request = await _create_request(uow_factory)
    await _create_run(uow_factory, request.request_id, attempt_number=1)
    # a second non-terminal run for the same request violates the partial unique index
    with pytest.raises(PersistenceError):
        await _create_run(uow_factory, request.request_id, attempt_number=2)


async def test_research_run_new_attempt_allowed_after_previous_run_is_terminal(uow_factory) -> None:
    request = await _create_request(uow_factory)
    first_run = await _create_run(uow_factory, request.request_id, attempt_number=1)
    async with uow_factory() as uow:
        await uow.research_runs.mark_failed(
            first_run.run_id, completed_at=NOW, failure_category=FailureCategory.PROVIDER_ERROR,
            failure_message="The provider timed out.", retryable=True,
        )
        await uow.commit()
    second_run = await _create_run(uow_factory, request.request_id, attempt_number=2)
    assert second_run.attempt_number == 2


async def test_research_run_get_max_attempt_number(uow_factory) -> None:
    request = await _create_request(uow_factory)
    async with uow_factory() as uow:
        zero = await uow.research_runs.get_max_attempt_number(request.request_id)
    assert zero == 0

    await _create_run(uow_factory, request.request_id, attempt_number=1)
    async with uow_factory() as uow:
        one = await uow.research_runs.get_max_attempt_number(request.request_id)
    assert one == 1


async def test_research_run_get_active_run_for_request(uow_factory) -> None:
    request = await _create_request(uow_factory)
    run = await _create_run(uow_factory, request.request_id, attempt_number=1)
    async with uow_factory() as uow:
        active = await uow.research_runs.get_active_run_for_request(request.request_id)
    assert active is not None
    assert active.run_id == run.run_id

    async with uow_factory() as uow:
        await uow.research_runs.mark_completed(run.run_id, completed_at=NOW)
        await uow.commit()

    async with uow_factory() as uow:
        active_after_completion = await uow.research_runs.get_active_run_for_request(request.request_id)
    assert active_after_completion is None


async def test_research_run_mark_running_then_get_with_for_update(uow_factory) -> None:
    request = await _create_request(uow_factory)
    run = await _create_run(uow_factory, request.request_id, attempt_number=1)
    async with uow_factory() as uow:
        started = await uow.research_runs.mark_running(run.run_id, started_at=NOW)
        await uow.commit()
    assert started.status == ResearchRunStatus.RUNNING

    async with uow_factory() as uow:
        locked = await uow.research_runs.get(run.run_id, for_update=True)
        await uow.commit()
    assert locked is not None
    assert locked.status == ResearchRunStatus.RUNNING


# ---------------------------------------------------------------------------
# EvidenceItem
# ---------------------------------------------------------------------------


async def test_evidence_item_round_trips(uow_factory) -> None:
    request = await _create_request(uow_factory)
    run = await _create_run(uow_factory, request.request_id)
    created = await _create_evidence(uow_factory, run.run_id)
    async with uow_factory() as uow:
        fetched = await uow.evidence_items.get(created.evidence_id)
    assert fetched is not None
    assert fetched.content_hash == created.content_hash


async def test_evidence_item_content_hash_is_unique_per_run(uow_factory) -> None:
    request = await _create_request(uow_factory)
    run = await _create_run(uow_factory, request.request_id)
    await _create_evidence(uow_factory, run.run_id)
    with pytest.raises(PersistenceError):
        await _create_evidence(uow_factory, run.run_id)


async def test_evidence_item_same_content_allowed_in_a_different_run(uow_factory) -> None:
    request = await _create_request(uow_factory)
    run_one = await _create_run(uow_factory, request.request_id, attempt_number=1)
    async with uow_factory() as uow:
        await uow.research_runs.mark_failed(
            run_one.run_id, completed_at=NOW, failure_category=FailureCategory.PROVIDER_ERROR,
            failure_message="failed", retryable=True,
        )
        await uow.commit()
    run_two = await _create_run(uow_factory, request.request_id, attempt_number=2)

    first = await _create_evidence(uow_factory, run_one.run_id)
    second = await _create_evidence(uow_factory, run_two.run_id)
    assert first.content_hash == second.content_hash
    assert first.evidence_id != second.evidence_id


async def test_evidence_item_list_for_run(uow_factory) -> None:
    request = await _create_request(uow_factory)
    run = await _create_run(uow_factory, request.request_id)
    await _create_evidence(uow_factory, run.run_id, source_title="Form 10-K")
    await _create_evidence(uow_factory, run.run_id, source_title="Form 10-Q", official_identifier="0001234567-26-000002")
    async with uow_factory() as uow:
        items = await uow.evidence_items.list_for_run(run.run_id)
    assert len(items) == 2


# ---------------------------------------------------------------------------
# EvidenceItem.list_page_for_run - database-level pagination (Phase G2C)
# ---------------------------------------------------------------------------


async def _create_many_evidence(uow_factory, run_id, count: int) -> list[EvidenceItem]:
    # Explicit, strictly increasing `retrieved_at` values (rather than the
    # real-wall-clock default) so pagination-order assertions below are
    # never flaky due to two items landing on the same timestamp - the
    # dedicated tiebreak test further down covers same-timestamp ordering.
    return [
        await _create_evidence(
            uow_factory, run_id, source_title=f"Form 10-K #{i}", official_identifier=f"0001234567-26-{i:06d}",
            retrieved_at=NOW.replace(microsecond=i * 1000),
        )
        for i in range(count)
    ]


async def test_list_page_for_run_first_page(uow_factory) -> None:
    request = await _create_request(uow_factory)
    run = await _create_run(uow_factory, request.request_id)
    created = await _create_many_evidence(uow_factory, run.run_id, 5)

    async with uow_factory() as uow:
        page = await uow.evidence_items.list_page_for_run(run.run_id, limit=3, offset=0)

    assert len(page) == 3
    assert [item.evidence_id for item in page] == [item.evidence_id for item in created[:3]]


async def test_list_page_for_run_later_page(uow_factory) -> None:
    request = await _create_request(uow_factory)
    run = await _create_run(uow_factory, request.request_id)
    created = await _create_many_evidence(uow_factory, run.run_id, 5)

    async with uow_factory() as uow:
        page = await uow.evidence_items.list_page_for_run(run.run_id, limit=3, offset=3)

    assert len(page) == 2
    assert [item.evidence_id for item in page] == [item.evidence_id for item in created[3:5]]


async def test_list_page_for_run_empty_final_page(uow_factory) -> None:
    request = await _create_request(uow_factory)
    run = await _create_run(uow_factory, request.request_id)
    await _create_many_evidence(uow_factory, run.run_id, 3)

    async with uow_factory() as uow:
        page = await uow.evidence_items.list_page_for_run(run.run_id, limit=10, offset=3)

    assert page == []


async def test_list_page_for_run_requesting_limit_plus_one_reveals_has_more(uow_factory) -> None:
    """The router asks the repository for `limit + 1` rows to compute
    `has_more` without a separate `COUNT(*)` - verify the repository
    actually returns that extra row when it exists, and does not when it
    does not, so the router's `has_more = len(rows) > limit` is accurate."""
    request = await _create_request(uow_factory)
    run = await _create_run(uow_factory, request.request_id)
    await _create_many_evidence(uow_factory, run.run_id, 4)

    async with uow_factory() as uow:
        # Router page size 4, so it requests limit+1=5 rows - only 4 exist.
        rows_for_page_size_4 = await uow.evidence_items.list_page_for_run(run.run_id, limit=5, offset=0)
        # Router page size 3, so it requests limit+1=4 rows - exactly 4 exist (the 4th reveals has_more).
        rows_for_page_size_3 = await uow.evidence_items.list_page_for_run(run.run_id, limit=4, offset=0)

    assert len(rows_for_page_size_4) == 4  # has_more would be False: len(rows) (4) is not > page size (4)
    assert len(rows_for_page_size_3) == 4  # has_more would be True: len(rows) (4) is > page size (3)


async def test_list_page_for_run_ordering_is_deterministic_with_evidence_id_tiebreak(uow_factory) -> None:
    """Two items sharing the same `retrieved_at` must still paginate
    deterministically - `evidence_id` breaks the tie."""
    request = await _create_request(uow_factory)
    run = await _create_run(uow_factory, request.request_id)
    shared_retrieved_at = NOW
    items = []
    for i in range(4):
        kwargs = _evidence_kwargs(
            source_title=f"Tied #{i}", official_identifier=f"0001234567-26-900{i:03d}", retrieved_at=shared_retrieved_at,
        )
        content_hash = compute_evidence_content_hash(
            source_type=kwargs["source_type"].value, classification=kwargs["classification"].value,
            source_url=kwargs["source_url"], official_identifier=kwargs["official_identifier"],
            source_title=kwargs["source_title"], publisher=kwargs["publisher"], published_at=kwargs["published_at"],
            raw_excerpt=kwargs["raw_excerpt"], normalized_text=kwargs["normalized_text"],
            structured_facts=kwargs["structured_facts"],
        )
        item = EvidenceItem(run_id=run.run_id, content_hash=content_hash, **kwargs)
        async with uow_factory() as uow:
            created = await uow.evidence_items.create(item)
            await uow.commit()
        items.append(created)
    expected_order = sorted(items, key=lambda item: item.evidence_id)

    async with uow_factory() as uow:
        page_one = await uow.evidence_items.list_page_for_run(run.run_id, limit=2, offset=0)
        page_two = await uow.evidence_items.list_page_for_run(run.run_id, limit=2, offset=2)

    assert [item.evidence_id for item in page_one + page_two] == [item.evidence_id for item in expected_order]
    # Repeated reads return the identical order - no row is skipped or repeated.
    async with uow_factory() as uow:
        page_one_again = await uow.evidence_items.list_page_for_run(run.run_id, limit=2, offset=0)
    assert [item.evidence_id for item in page_one] == [item.evidence_id for item in page_one_again]


async def test_list_page_for_run_does_not_include_other_runs_evidence(uow_factory) -> None:
    request = await _create_request(uow_factory)
    run_one = await _create_run(uow_factory, request.request_id, attempt_number=1)
    async with uow_factory() as uow:
        await uow.research_runs.mark_failed(
            run_one.run_id, completed_at=NOW, failure_category=FailureCategory.PROVIDER_ERROR,
            failure_message="failed", retryable=True,
        )
        await uow.commit()
    run_two = await _create_run(uow_factory, request.request_id, attempt_number=2)

    await _create_evidence(uow_factory, run_one.run_id, source_title="Run one evidence")
    await _create_evidence(uow_factory, run_two.run_id, source_title="Run two evidence", official_identifier="0001234567-26-777777")

    async with uow_factory() as uow:
        page = await uow.evidence_items.list_page_for_run(run_two.run_id, limit=10, offset=0)

    assert len(page) == 1
    assert page[0].source_title == "Run two evidence"


# ---------------------------------------------------------------------------
# ResearchClaim + ClaimEvidenceLink
# ---------------------------------------------------------------------------


async def test_research_claim_round_trips(uow_factory) -> None:
    request = await _create_request(uow_factory)
    run = await _create_run(uow_factory, request.request_id)
    created = await _create_claim(uow_factory, run.run_id)
    async with uow_factory() as uow:
        fetched = await uow.research_claims.get(created.claim_id)
    assert fetched is not None
    assert fetched.claim_text == created.claim_text


async def test_claim_evidence_link_create_and_list(uow_factory) -> None:
    request = await _create_request(uow_factory)
    run = await _create_run(uow_factory, request.request_id)
    claim = await _create_claim(uow_factory, run.run_id)
    evidence = await _create_evidence(uow_factory, run.run_id)

    async with uow_factory() as uow:
        link = await uow.claim_evidence_links.create_link(claim.claim_id, evidence.evidence_id, EvidenceStance.SUPPORTS)
        await uow.commit()
    assert link.stance == EvidenceStance.SUPPORTS

    async with uow_factory() as uow:
        by_claim = await uow.claim_evidence_links.list_links_for_claim(claim.claim_id)
        by_evidence = await uow.claim_evidence_links.list_links_for_evidence(evidence.evidence_id)
    assert len(by_claim) == 1
    assert len(by_evidence) == 1
    assert by_claim[0].link_id == link.link_id


async def test_claim_evidence_link_rejects_duplicate_pair(uow_factory) -> None:
    request = await _create_request(uow_factory)
    run = await _create_run(uow_factory, request.request_id)
    claim = await _create_claim(uow_factory, run.run_id)
    evidence = await _create_evidence(uow_factory, run.run_id)

    async with uow_factory() as uow:
        await uow.claim_evidence_links.create_link(claim.claim_id, evidence.evidence_id, EvidenceStance.SUPPORTS)
        await uow.commit()

    with pytest.raises(DuplicateClaimEvidenceLinkError):
        async with uow_factory() as uow:
            await uow.claim_evidence_links.create_link(claim.claim_id, evidence.evidence_id, EvidenceStance.CONTRADICTS)
            await uow.commit()


async def test_research_claim_update_status(uow_factory) -> None:
    request = await _create_request(uow_factory)
    run = await _create_run(uow_factory, request.request_id)
    claim = await _create_claim(uow_factory, run.run_id)

    async with uow_factory() as uow:
        from stock_research_core.domain.live_research.enums import ClaimStatus

        updated = await uow.research_claims.update_status(claim.claim_id, ClaimStatus.CORROBORATED, confidence_score=0.9)
        await uow.commit()
    assert updated.status == ClaimStatus.CORROBORATED
    assert updated.confidence_score == pytest.approx(0.9)
