"""Unit tests for `live_research_job_resource_key` (Phase G2B).

Verifies the key uses trusted requester identity plus a bounded hash of
the trusted idempotency key - never the raw idempotency key, the
research question, an API secret, or a `request_id` (which does not
exist at job-creation time).
"""

from __future__ import annotations

from uuid import uuid4

from stock_research_core.application.operations.locking import live_research_job_resource_key
from stock_research_core.application.operations.ports import JobExecutionContext
from stock_research_core.domain.operations.enums import BackgroundJobType, JobTriggerSource

_JOB_TYPE = BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION


def _context(**overrides) -> JobExecutionContext:
    fields = dict(
        job_id=uuid4(), job_type=_JOB_TYPE, trigger_source=JobTriggerSource.ADMIN_CLI,
        requested_by_account_id=None, requested_by_integration_id=None,
        idempotency_key="secret-idempotency-key-value", correlation_id=None, attempt_number=0,
    )
    fields.update(overrides)
    return JobExecutionContext(**fields)


class TestLiveResearchJobResourceKey:
    def test_account_identity_is_embedded_in_the_key(self) -> None:
        account_id = uuid4()
        key = live_research_job_resource_key(_context(requested_by_account_id=account_id))
        assert key.startswith(f"live-research-job:account:{account_id}:")

    def test_integration_identity_is_embedded_in_the_key(self) -> None:
        integration_id = uuid4()
        key = live_research_job_resource_key(_context(requested_by_integration_id=integration_id))
        assert key.startswith(f"live-research-job:integration:{integration_id}:")

    def test_neither_identity_set_falls_back_to_trigger_source_without_raising(self) -> None:
        key = live_research_job_resource_key(_context(trigger_source=JobTriggerSource.SYSTEM))
        assert key.startswith("live-research-job:source:SYSTEM:")

    def test_account_identity_takes_precedence_over_integration_identity(self) -> None:
        account_id, integration_id = uuid4(), uuid4()
        key = live_research_job_resource_key(
            _context(requested_by_account_id=account_id, requested_by_integration_id=integration_id)
        )
        assert f"account:{account_id}" in key
        assert f"integration:{integration_id}" not in key

    def test_idempotency_key_is_hashed_and_never_appears_verbatim(self) -> None:
        raw_idempotency_key = "sk-super-secret-idempotency-token"
        key = live_research_job_resource_key(_context(idempotency_key=raw_idempotency_key))
        assert raw_idempotency_key not in key

    def test_research_question_and_secrets_never_appear(self) -> None:
        # The key is built purely from JobExecutionContext, which never
        # carries a question, provider API key, or request_id at all -
        # this test documents that guarantee structurally.
        context = _context()
        key = live_research_job_resource_key(context)
        assert "request_id" not in key
        for forbidden in ("what is a bond", "sk-", "api_key"):
            assert forbidden not in key.lower()

    def test_deterministic_for_identical_inputs(self) -> None:
        account_id = uuid4()
        context = _context(requested_by_account_id=account_id, idempotency_key="same-key")
        key1 = live_research_job_resource_key(context)
        key2 = live_research_job_resource_key(context)
        assert key1 == key2

    def test_different_idempotency_keys_produce_different_keys(self) -> None:
        account_id = uuid4()
        key1 = live_research_job_resource_key(_context(requested_by_account_id=account_id, idempotency_key="key-a"))
        key2 = live_research_job_resource_key(_context(requested_by_account_id=account_id, idempotency_key="key-b"))
        assert key1 != key2

    def test_different_requesters_produce_different_keys_for_the_same_idempotency_key(self) -> None:
        key1 = live_research_job_resource_key(_context(requested_by_account_id=uuid4(), idempotency_key="same"))
        key2 = live_research_job_resource_key(_context(requested_by_account_id=uuid4(), idempotency_key="same"))
        assert key1 != key2

    def test_key_respects_the_persisted_resource_key_length_bound(self) -> None:
        # BackgroundJob.resource_key: Field(default=None, max_length=300).
        key = live_research_job_resource_key(_context(requested_by_account_id=uuid4()))
        assert len(key) <= 300

    def test_never_uses_a_request_id_shaped_key(self) -> None:
        # Not a literal test of a forbidden argument (the function has no
        # request_id parameter at all) - documents that the function
        # signature itself makes this impossible.
        import inspect

        signature = inspect.signature(live_research_job_resource_key)
        assert "request_id" not in signature.parameters
