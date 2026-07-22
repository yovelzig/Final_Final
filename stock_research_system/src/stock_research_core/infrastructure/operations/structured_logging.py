"""Structured logging configuration: development gets human-readable
console output, production gets one JSON object per line. Every log
record - both new `structlog` call sites and the existing stdlib
`logging.getLogger(...)` call sites elsewhere in the codebase - passes
through the same recursive redaction filter before it is ever rendered.

`configure_structlog()` is called exactly once, at process startup
(`api.app_factory.create_app()` or a Celery worker entry point) - never
at import time.
"""

from __future__ import annotations

import logging
from typing import Any

import structlog

from stock_research_core.domain.operations.sanitization import redact

_DEFAULT_KEYS_NEVER_REDACTED = frozenset({"event", "level", "timestamp", "logger"})


def _redact_processor(_logger: Any, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact sensitive values in every log event, without
    touching structlog's own bookkeeping keys."""
    redacted: dict[str, Any] = {}
    for key, value in event_dict.items():
        if key in _DEFAULT_KEYS_NEVER_REDACTED:
            redacted[key] = value
        else:
            redacted[key] = redact({key: value})[key]
    return redacted


def _bind_service_processor(service: str, environment: str):
    def _processor(_logger: Any, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        event_dict.setdefault("service", service)
        event_dict.setdefault("environment", environment)
        return event_dict

    return _processor


def configure_structlog(
    *, environment: str, service_name: str = "finquest-api", json_output: bool | None = None, stream: Any = None,
) -> None:
    """Configure both `structlog` and stdlib `logging` to render through
    the same processor chain. `json_output` defaults to `environment ==
    "production"` but can be overridden (e.g. tests forcing JSON output
    to assert on it regardless of environment)."""
    is_json = json_output if json_output is not None else (environment == "production")

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        _bind_service_processor(service_name, environment),
        _redact_processor,
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer = structlog.processors.JSONRenderer() if is_json else structlog.dev.ConsoleRenderer()
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    handler = logging.StreamHandler(stream) if stream is not None else logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging.INFO)


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)


def bind_job_log_context(
    *, job_id: str, job_type: str, attempt_number: int, queue: str, worker_name: str | None = None,
    correlation_id: str | None = None,
) -> None:
    structlog.contextvars.bind_contextvars(
        job_id=job_id, job_type=job_type, attempt_number=attempt_number, queue=queue,
        worker_name=worker_name, correlation_id=correlation_id,
    )


def clear_log_context() -> None:
    structlog.contextvars.clear_contextvars()
