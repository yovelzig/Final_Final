"""`JobQueuePort` implementation backed by Celery.

The Celery task payload carries only `job_id` (a string, JSON-encoded) -
never the job's parameters. Workers always reload parameters from
PostgreSQL via `BackgroundJobService.execute_job`, never trust anything
else riding along on the message.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from uuid import UUID

from celery import Celery

from stock_research_core.domain.models import utc_now
from stock_research_core.domain.operations.enums import BackgroundJobPriority, BackgroundJobType


class CeleryJobQueue:
    def __init__(self, celery_app: Celery) -> None:
        self._celery_app = celery_app

    async def enqueue(
        self,
        *,
        job_id: UUID,
        job_type: BackgroundJobType,
        queue_name: str,
        priority: BackgroundJobPriority,
        available_at: datetime,
    ) -> str:
        task_name = f"finquest.{job_type.value.lower()}"
        eta = available_at if available_at > utc_now() else None

        def _send() -> Any:
            return self._celery_app.send_task(
                task_name, kwargs={"job_id": str(job_id)}, queue=queue_name, eta=eta,
            )

        # `send_task` performs blocking network I/O against the broker
        # (Kombu's Redis transport is synchronous) - run it off the event
        # loop rather than blocking every concurrent request.
        async_result = await asyncio.to_thread(_send)
        return async_result.id
