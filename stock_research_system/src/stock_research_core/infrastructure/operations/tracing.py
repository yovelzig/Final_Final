"""Optional OpenTelemetry tracing, satisfying `TracingPort`.

Disabled by default (`OTEL_ENABLED=false`): `NoOpTracing` is used, no
collector is required, and no error is ever produced. When enabled and
the `opentelemetry-*` optional dependencies are not installed, this
module logs a warning once and falls back to the no-op tracer rather
than crashing the process - tracing is always allowed to be
best-effort.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

logger = logging.getLogger("stock_research_core.infrastructure.operations.tracing")

_SAFE_ATTRIBUTE_TYPES = (str, int, float, bool)


def _sanitize_attributes(attributes: dict[str, Any] | None) -> dict[str, str | int | float | bool]:
    """Keep only bounded, low-cardinality, non-sensitive attribute values -
    never raw question text, journal rationale, or document content."""
    if not attributes:
        return {}
    safe: dict[str, str | int | float | bool] = {}
    for key, value in attributes.items():
        if isinstance(value, _SAFE_ATTRIBUTE_TYPES):
            safe[key] = value[:200] if isinstance(value, str) else value
    return safe


class NoOpTracing:
    @asynccontextmanager
    async def start_span(self, name: str, *, attributes: dict[str, Any] | None = None) -> AsyncIterator[None]:
        yield


class OpenTelemetryTracing:
    """Wraps an OpenTelemetry `Tracer`. Only constructed when
    `OTEL_ENABLED=true` and the optional dependency is importable."""

    def __init__(self, tracer: Any) -> None:
        self._tracer = tracer

    @asynccontextmanager
    async def start_span(self, name: str, *, attributes: dict[str, Any] | None = None) -> AsyncIterator[None]:
        with self._tracer.start_as_current_span(name, attributes=_sanitize_attributes(attributes)):
            yield


def build_tracing(*, enabled: bool, service_name: str, otlp_endpoint: str, sample_ratio: float) -> Any:
    """Returns a `TracingPort`-satisfying object: a real OTel-backed
    tracer when enabled and available, otherwise the safe no-op."""
    if not enabled:
        return NoOpTracing()

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
    except ImportError:
        logger.warning(
            "OTEL_ENABLED=true but the optional opentelemetry dependencies are not installed "
            "(pip install '.[otel]'); falling back to no-op tracing."
        )
        return NoOpTracing()

    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource, sampler=TraceIdRatioBased(sample_ratio))

    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
        except ImportError:
            logger.warning("OTEL_EXPORTER_OTLP_ENDPOINT is set but the OTLP exporter is not installed; spans will not be exported.")

    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer(service_name)
    return OpenTelemetryTracing(tracer)


def instrument_fastapi_app(app: Any, *, enabled: bool) -> None:
    if not enabled:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except ImportError:
        logger.warning("OTEL_ENABLED=true but opentelemetry-instrumentation-fastapi is not installed; skipping.")
