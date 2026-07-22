"""Unit tests for the Phase 11 operations domain models
(`domain.operations.models`) - lifecycle validation, progress rules,
attempt/event sanitization, and integration-client invariants.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from stock_research_core.domain.operations.enums import (
    BackgroundJobStatus,
    BackgroundJobType,
    IntegrationClientStatus,
    JobAttemptStatus,
    JobEventType,
    JobTriggerSource,
)
from stock_research_core.domain.operations.models import (
    BackgroundJob,
    BackgroundJobAttempt,
    BackgroundJobEvent,
    IntegrationClient,
    IntegrationRequest,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _job(**overrides) -> BackgroundJob:
    fields = dict(
        job_type=BackgroundJobType.PORTFOLIO_VALUATION, trigger_source=JobTriggerSource.API,
        idempotency_key="k1", queue_name="finquest.portfolio", task_name="finquest.portfolio_valuation",
    )
    fields.update(overrides)
    return BackgroundJob(**fields)


class TestBackgroundJobLifecycle:
    def test_pending_job_defaults(self) -> None:
        job = _job()
        assert job.status == BackgroundJobStatus.PENDING
        assert job.attempt_count == 0

    def test_running_requires_started_at(self) -> None:
        with pytest.raises(ValidationError, match="RUNNING job requires started_at"):
            _job(status=BackgroundJobStatus.RUNNING)

    def test_running_with_started_at_is_valid(self) -> None:
        job = _job(status=BackgroundJobStatus.RUNNING, started_at=NOW)
        assert job.status == BackgroundJobStatus.RUNNING

    @pytest.mark.parametrize("status", [BackgroundJobStatus.SUCCEEDED, BackgroundJobStatus.FAILED, BackgroundJobStatus.SKIPPED])
    def test_terminal_statuses_require_completed_at(self, status: BackgroundJobStatus) -> None:
        kwargs = {"status": status}
        if status == BackgroundJobStatus.SUCCEEDED:
            kwargs["result_summary"] = {"ok": True}
        with pytest.raises(ValidationError, match="requires completed_at"):
            _job(**kwargs)

    def test_cancelled_accepts_cancelled_at_without_completed_at(self) -> None:
        job = _job(status=BackgroundJobStatus.CANCELLED, cancelled_at=NOW)
        assert job.status == BackgroundJobStatus.CANCELLED

    def test_succeeded_requires_result_summary(self) -> None:
        with pytest.raises(ValidationError, match="requires a result_summary"):
            _job(status=BackgroundJobStatus.SUCCEEDED, completed_at=NOW)

    def test_succeeded_with_result_summary_is_valid(self) -> None:
        job = _job(status=BackgroundJobStatus.SUCCEEDED, completed_at=NOW, result_summary={"bars_inserted": 10})
        assert job.result_summary == {"bars_inserted": 10}

    @pytest.mark.parametrize("sensitive_params", [
        {"password": "hunter2"},
        {"database_url": "postgresql://user:pass@host/db"},
        {"nested": {"api_key": "secret"}},
        {"refresh_token": "abc"},
    ])
    def test_parameters_reject_sensitive_fields(self, sensitive_params: dict) -> None:
        with pytest.raises(ValidationError, match="sensitive"):
            _job(parameters=sensitive_params)

    def test_result_summary_rejects_traceback(self) -> None:
        with pytest.raises(ValidationError, match="traceback"):
            _job(
                status=BackgroundJobStatus.FAILED, completed_at=NOW,
                result_summary={"error": "Traceback (most recent call last):\n  File x"},
            )

    def test_progress_current_cannot_exceed_total(self) -> None:
        with pytest.raises(ValidationError, match="cannot exceed"):
            _job(progress_current=10, progress_total=5)

    def test_progress_current_equal_to_total_is_valid(self) -> None:
        job = _job(progress_current=5, progress_total=5)
        assert job.progress_current == 5

    def test_maximum_attempts_bounds(self) -> None:
        with pytest.raises(ValidationError):
            _job(maximum_attempts=0)
        with pytest.raises(ValidationError):
            _job(maximum_attempts=21)

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _job(unexpected_field="nope")

    def test_empty_idempotency_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _job(idempotency_key="")


class TestBackgroundJobAttempt:
    def _attempt(self, **overrides) -> BackgroundJobAttempt:
        fields = dict(job_id=uuid4(), attempt_number=1, started_at=NOW)
        fields.update(overrides)
        return BackgroundJobAttempt(**fields)

    def test_attempt_number_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            self._attempt(attempt_number=0)

    def test_terminal_status_requires_completed_at(self) -> None:
        with pytest.raises(ValidationError, match="requires completed_at"):
            self._attempt(status=JobAttemptStatus.SUCCEEDED)

    def test_failed_requires_sanitized_error_fields(self) -> None:
        with pytest.raises(ValidationError, match="requires sanitized error_type"):
            self._attempt(status=JobAttemptStatus.FAILED, completed_at=NOW)

    def test_failed_with_error_fields_is_valid(self) -> None:
        attempt = self._attempt(
            status=JobAttemptStatus.FAILED, completed_at=NOW, error_type="ValueError", error_message="bad input",
        )
        assert attempt.error_type == "ValueError"

    def test_error_message_rejects_traceback(self) -> None:
        with pytest.raises(ValidationError, match="traceback"):
            self._attempt(
                status=JobAttemptStatus.FAILED, completed_at=NOW, error_type="X",
                error_message="Traceback (most recent call last):\nfoo",
            )

    def test_error_message_rejects_jwt_shaped_content(self) -> None:
        jwt_like = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dQw4w9WgXcQ_abcdefghijklmno"
        with pytest.raises(ValidationError, match="credential"):
            self._attempt(status=JobAttemptStatus.FAILED, completed_at=NOW, error_type="X", error_message=jwt_like)

    def test_retry_delay_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            self._attempt(retry_delay_seconds=-1)


class TestBackgroundJobEvent:
    def test_event_is_immutable(self) -> None:
        event = BackgroundJobEvent(job_id=uuid4(), event_type=JobEventType.CREATED, message="Job created.")
        with pytest.raises(ValidationError):
            event.message = "changed"

    def test_message_must_be_ascii(self) -> None:
        with pytest.raises(ValidationError, match="ASCII"):
            BackgroundJobEvent(job_id=uuid4(), event_type=JobEventType.CREATED, message="job créé")

    def test_metadata_rejects_sensitive_fields(self) -> None:
        with pytest.raises(ValidationError, match="sensitive"):
            BackgroundJobEvent(
                job_id=uuid4(), event_type=JobEventType.CREATED, message="Job created.",
                metadata={"authorization": "Bearer xyz"},
            )

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BackgroundJobEvent(
                job_id=uuid4(), event_type=JobEventType.CREATED, message="Job created.", unexpected="nope"
            )


class TestIntegrationClient:
    def test_allowed_job_types_must_be_unique(self) -> None:
        with pytest.raises(ValidationError, match="duplicates"):
            IntegrationClient(
                name="n8n", key_id="k1", api_key_hash="h" * 64,
                allowed_job_types=[BackgroundJobType.RETRIEVAL_EVALUATION, BackgroundJobType.RETRIEVAL_EVALUATION],
            )

    def test_active_requires_at_least_one_allowed_job_type(self) -> None:
        with pytest.raises(ValidationError, match="at least one allowed job type"):
            IntegrationClient(
                name="n8n", key_id="k1", api_key_hash="h" * 64,
                status=IntegrationClientStatus.ACTIVE, allowed_job_types=[],
            )

    def test_disabled_client_may_have_no_allowed_job_types(self) -> None:
        client = IntegrationClient(
            name="n8n", key_id="k1", api_key_hash="h" * 64,
            status=IntegrationClientStatus.DISABLED, allowed_job_types=[],
        )
        assert client.allowed_job_types == []

    def test_never_carries_a_raw_api_key_field(self) -> None:
        assert "api_key" not in IntegrationClient.model_fields
        assert "raw_key" not in IntegrationClient.model_fields


class TestIntegrationRequest:
    def _request(self, **overrides) -> IntegrationRequest:
        fields = dict(
            integration_id=uuid4(), external_request_id="req-1", idempotency_key="idem-1",
            request_hash="a" * 64, correlation_id="corr-1",
        )
        fields.update(overrides)
        return IntegrationRequest(**fields)

    def test_request_hash_must_be_lowercase_hex_sha256(self) -> None:
        with pytest.raises(ValidationError, match="lowercase"):
            self._request(request_hash="A" * 64)
        with pytest.raises(ValidationError):
            self._request(request_hash="short")

    def test_valid_request_hash_accepted(self) -> None:
        request = self._request(request_hash="f" * 64)
        assert request.request_hash == "f" * 64
