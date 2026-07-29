"""Regression tests for Celery's process-owned asyncio loop."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from stock_research_core.application.language.unavailable_language_service import (
    UnavailableLanguageService,
)
from stock_research_core.infrastructure.operations import celery_tasks


@pytest.fixture(autouse=True)
def _reset_worker_lifecycle() -> Any:
    celery_tasks._worker_context = None
    celery_tasks._stop_worker_event_loop()

    yield

    celery_tasks._worker_context = None
    celery_tasks._stop_worker_event_loop()


async def _current_loop_and_thread() -> tuple[
    asyncio.AbstractEventLoop,
    int,
]:
    return asyncio.get_running_loop(), threading.get_ident()


def test_run_async_reuses_one_process_loop() -> None:
    first_loop, first_thread = celery_tasks._run_async(
        _current_loop_and_thread()
    )
    second_loop, second_thread = celery_tasks._run_async(
        _current_loop_and_thread()
    )

    assert first_loop is second_loop
    assert first_thread == second_thread
    assert first_thread != threading.get_ident()


def test_shutdown_closes_context_on_owner_loop() -> None:
    created_loop, _ = celery_tasks._run_async(
        _current_loop_and_thread()
    )
    closed_on: list[asyncio.AbstractEventLoop] = []

    class _RecordingPool:
        async def close(self) -> None:
            closed_on.append(asyncio.get_running_loop())

    celery_tasks._worker_context = celery_tasks.WorkerContext(
        engine=None,
        redis_client=None,
        service=None,
        registry=None,
        language_service=UnavailableLanguageService(),
        learning_orchestrator_checkpointer_pool=_RecordingPool(),
    )

    celery_tasks._shutdown_worker_process()

    assert closed_on == [created_loop]
    assert celery_tasks._worker_context is None
    assert celery_tasks._worker_event_loop is None
    assert celery_tasks._worker_event_loop_thread is None


def test_shutdown_without_context_stops_loop() -> None:
    celery_tasks._run_async(
        _current_loop_and_thread()
    )

    celery_tasks._worker_context = None
    celery_tasks._shutdown_worker_process()

    assert celery_tasks._worker_event_loop is None
    assert celery_tasks._worker_event_loop_thread is None


def test_loop_can_be_recreated_after_shutdown() -> None:
    first_loop, _ = celery_tasks._run_async(
        _current_loop_and_thread()
    )

    celery_tasks._shutdown_worker_process()

    second_loop, _ = celery_tasks._run_async(
        _current_loop_and_thread()
    )

    assert second_loop is not first_loop
