"""The Celery application object.

Constructing a `Celery(...)` instance does not open a broker connection
(Celery/Kombu connect lazily, on first `send_task`/worker-consume) - safe
to build once at import time, exactly like every other Celery project's
`celery_app = Celery(...)` module-level singleton. No network I/O happens
here.
"""

from __future__ import annotations

from celery import Celery

from stock_research_core.infrastructure.operations.config import OperationsSettings

QUEUE_DEFAULT = "finquest.default"
QUEUE_MARKET = "finquest.market"
QUEUE_PORTFOLIO = "finquest.portfolio"
QUEUE_KNOWLEDGE = "finquest.knowledge"
QUEUE_EVALUATION = "finquest.evaluation"

ALL_QUEUES = (QUEUE_DEFAULT, QUEUE_MARKET, QUEUE_PORTFOLIO, QUEUE_KNOWLEDGE, QUEUE_EVALUATION)


def build_celery_app(settings: OperationsSettings | None = None) -> Celery:
    settings = settings or OperationsSettings()
    app = Celery("finquest")
    app.conf.update(
        broker_url=settings.resolved_celery_broker_url,
        result_backend=settings.resolved_celery_result_backend,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_acks_late=settings.celery_task_acks_late,
        worker_prefetch_multiplier=max(1, settings.celery_worker_prefetch_multiplier),
        task_reject_on_worker_lost=True,
        task_default_queue=QUEUE_DEFAULT,
        task_queues={queue: {} for queue in ALL_QUEUES},
        broker_connection_retry_on_startup=True,
        worker_hijack_root_logger=False,
    )
    return app


celery_app = build_celery_app()
