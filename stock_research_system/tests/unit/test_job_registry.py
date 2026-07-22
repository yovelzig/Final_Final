"""Unit tests for `BackgroundJobRegistry` and the default retry policies."""

from __future__ import annotations

import pytest

from stock_research_core.application.operations.job_registry import (
    BackgroundJobRegistry,
    ExponentialBackoffRetryPolicy,
    FixedScheduleRetryPolicy,
    JobRegistryEntry,
    NeverRetryPolicy,
    build_default_registry,
)
from stock_research_core.application.operations.models import PortfolioValuationParameters
from stock_research_core.domain.operations.enums import BackgroundJobType, JobTriggerSource


def _minimal_entry(job_type: BackgroundJobType, **overrides) -> JobRegistryEntry:
    fields = dict(
        job_type=job_type, parameter_model=PortfolioValuationParameters, queue_name="finquest.default",
        task_name=f"finquest.{job_type.value.lower()}", handler=object(), maximum_attempts=3,
        retry_policy=NeverRetryPolicy(), time_limit_seconds=60, resource_key_builder=lambda p: None,
        allowed_trigger_sources=frozenset(JobTriggerSource),
    )
    fields.update(overrides)
    return JobRegistryEntry(**fields)


def _all_entries(**overrides_by_type) -> list[JobRegistryEntry]:
    return [_minimal_entry(job_type, **overrides_by_type.get(job_type, {})) for job_type in BackgroundJobType]


class TestBackgroundJobRegistry:
    def test_fails_when_a_job_type_is_missing(self) -> None:
        entries = _all_entries()[:-1]
        with pytest.raises(ValueError, match="Missing job registry entries"):
            BackgroundJobRegistry(entries)

    def test_fails_when_a_job_type_is_registered_twice(self) -> None:
        entries = _all_entries()
        entries.append(_minimal_entry(BackgroundJobType.PORTFOLIO_VALUATION))
        with pytest.raises(ValueError, match="registered more than once"):
            BackgroundJobRegistry(entries)

    def test_fails_when_handler_is_none(self) -> None:
        entries = _all_entries()
        entries[0] = _minimal_entry(entries[0].job_type, handler=None)
        with pytest.raises(ValueError, match="no handler"):
            BackgroundJobRegistry(entries)

    def test_fails_when_queue_name_is_empty(self) -> None:
        entries = _all_entries()
        entries[0] = _minimal_entry(entries[0].job_type, queue_name="")
        with pytest.raises(ValueError, match="empty queue name"):
            BackgroundJobRegistry(entries)

    def test_fails_when_task_name_is_empty(self) -> None:
        entries = _all_entries()
        entries[0] = _minimal_entry(entries[0].job_type, task_name="")
        with pytest.raises(ValueError, match="empty task name"):
            BackgroundJobRegistry(entries)

    @pytest.mark.parametrize("maximum_attempts", [0, 21])
    def test_fails_on_invalid_maximum_attempts(self, maximum_attempts: int) -> None:
        entries = _all_entries()
        entries[0] = _minimal_entry(entries[0].job_type, maximum_attempts=maximum_attempts)
        with pytest.raises(ValueError, match="maximum_attempts"):
            BackgroundJobRegistry(entries)

    def test_fails_when_no_trigger_sources_allowed(self) -> None:
        entries = _all_entries()
        entries[0] = _minimal_entry(entries[0].job_type, allowed_trigger_sources=frozenset())
        with pytest.raises(ValueError, match="allows no trigger sources"):
            BackgroundJobRegistry(entries)

    def test_successful_construction_resolves_every_job_type(self) -> None:
        registry = BackgroundJobRegistry(_all_entries())
        for job_type in BackgroundJobType:
            entry = registry.get(job_type)
            assert entry.job_type == job_type

    def test_get_unknown_job_type_raises(self) -> None:
        registry = BackgroundJobRegistry(_all_entries())
        with pytest.raises(ValueError):
            registry.get("NOT_A_REAL_TYPE")  # type: ignore[arg-type]


class TestBuildDefaultRegistry:
    def test_fails_when_a_handler_is_missing(self) -> None:
        handlers = {job_type: object() for job_type in list(BackgroundJobType)[:-1]}
        with pytest.raises(ValueError, match="No handler supplied"):
            build_default_registry(handlers)

    def test_succeeds_with_every_handler_supplied(self) -> None:
        handlers = {job_type: object() for job_type in BackgroundJobType}
        registry = build_default_registry(handlers)
        assert registry.all_queue_names() == {
            "finquest.default", "finquest.market", "finquest.portfolio", "finquest.knowledge", "finquest.evaluation",
        }
        entry = registry.get(BackgroundJobType.SYSTEM_MAINTENANCE)
        assert JobTriggerSource.API not in entry.allowed_trigger_sources
        assert JobTriggerSource.N8N not in entry.allowed_trigger_sources
        assert JobTriggerSource.ADMIN_CLI in entry.allowed_trigger_sources


class TestFixedScheduleRetryPolicy:
    def test_non_retryable_exception_type_is_never_retried(self) -> None:
        policy = FixedScheduleRetryPolicy(maximum_attempts=4, delays_seconds=(30,), retryable_exceptions=(TimeoutError,))
        decision = policy.classify(ValueError("bad"), attempt_number=1)
        assert not decision.retryable

    def test_retryable_exception_retries_until_maximum_attempts(self) -> None:
        policy = FixedScheduleRetryPolicy(
            maximum_attempts=3, delays_seconds=(30, 120), retryable_exceptions=(TimeoutError,)
        )
        first = policy.classify(TimeoutError(), attempt_number=1)
        second = policy.classify(TimeoutError(), attempt_number=2)
        third = policy.classify(TimeoutError(), attempt_number=3)
        assert first.retryable and first.delay_seconds == 30
        assert second.retryable and second.delay_seconds == 120
        assert not third.retryable  # exhausted maximum_attempts

    def test_last_delay_repeats_beyond_schedule_length(self) -> None:
        policy = FixedScheduleRetryPolicy(maximum_attempts=5, delays_seconds=(30,), retryable_exceptions=(TimeoutError,))
        decision = policy.classify(TimeoutError(), attempt_number=4)
        assert decision.retryable and decision.delay_seconds == 30


class TestExponentialBackoffRetryPolicy:
    def test_delay_doubles_and_is_capped(self) -> None:
        policy = ExponentialBackoffRetryPolicy(
            maximum_attempts=6, base_delay_seconds=5, cap_seconds=40, retryable_exceptions=(TimeoutError,),
        )
        delays = [policy.classify(TimeoutError(), attempt_number=n).delay_seconds for n in range(1, 6)]
        assert delays == [5, 10, 20, 40, 40]

    def test_jitter_is_injectable_and_deterministic(self) -> None:
        policy = ExponentialBackoffRetryPolicy(
            maximum_attempts=3, base_delay_seconds=10, cap_seconds=100,
            retryable_exceptions=(TimeoutError,), jitter=lambda raw: raw + 1,
        )
        decision = policy.classify(TimeoutError(), attempt_number=1)
        assert decision.delay_seconds == 11


class TestNeverRetryPolicy:
    def test_always_non_retryable(self) -> None:
        policy = NeverRetryPolicy()
        decision = policy.classify(RuntimeError("boom"), attempt_number=1)
        assert not decision.retryable
