"""Unit tests for Celery task registration (Phase G2B addition).

Importing `celery_tasks` never opens a database, Redis, or Celery broker
connection - the worker composition root (`_build_worker_context`) is
built lazily on the `worker_process_init` signal, never at import time
(see the module's own docstring). Safe to import and inspect here.
"""

from __future__ import annotations

from stock_research_core.domain.operations.enums import BackgroundJobType
from stock_research_core.infrastructure.operations import celery_tasks


class TestLiveResearchRunExecutionTaskRegistration:
    def test_time_limit_is_180_seconds(self) -> None:
        assert celery_tasks._TIME_LIMITS[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION] == 180

    def test_task_is_registered_with_the_expected_name(self) -> None:
        task = celery_tasks.live_research_run_execution_task
        assert task.name == "finquest.live_research_run_execution"

    def test_task_soft_time_limit_is_80_percent_of_time_limit(self) -> None:
        task = celery_tasks.live_research_run_execution_task
        assert task.soft_time_limit == 144

    def test_task_uses_no_native_celery_retries(self) -> None:
        task = celery_tasks.live_research_run_execution_task
        assert task.max_retries == 0

    def test_task_acks_late(self) -> None:
        assert celery_tasks.live_research_run_execution_task.acks_late is True


class TestExistingTaskRegistrationUnaffected:
    """Regression guard: adding the new task must not remove, rename, or
    change the time limit of any of the 13 pre-existing task types."""

    def test_every_background_job_type_has_a_time_limit(self) -> None:
        for job_type in BackgroundJobType:
            assert job_type in celery_tasks._TIME_LIMITS

    def test_security_market_refresh_time_limit_unchanged(self) -> None:
        assert celery_tasks._TIME_LIMITS[BackgroundJobType.SECURITY_MARKET_REFRESH] == 300

    def test_system_maintenance_task_still_registered(self) -> None:
        assert celery_tasks.system_maintenance_task.name == "finquest.system_maintenance"
