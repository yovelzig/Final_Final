"""ASGI middleware: correlation IDs, security headers, and request logging.

None of these ever touch the `Authorization` header, cookies, or a
request/response body - only method, path, status, duration, and the
correlation ID are ever logged.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("stock_research_core.api.requests")

CORRELATION_ID_HEADER = "X-Correlation-ID"
_MAX_CORRELATION_ID_LENGTH = 128
_VALID_CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

# Every versioned API response is learner- or account-sensitive in this
# product, so `Cache-Control: no-store` is applied broadly rather than
# enumerated route by route (a deliberate simplification of spec ss17's
# "apply to authentication and sensitive learner responses").
_NO_STORE_PATH_PREFIX = "/api/"


def _generate_correlation_id() -> str:
    return str(uuid.uuid4())


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Accepts, validates, and echoes `X-Correlation-ID`; generates one when absent or malformed."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        raw = request.headers.get(CORRELATION_ID_HEADER)
        if raw and len(raw) <= _MAX_CORRELATION_ID_LENGTH and _VALID_CORRELATION_ID_PATTERN.fullmatch(raw):
            correlation_id = raw
        else:
            correlation_id = _generate_correlation_id()
        request.state.correlation_id = correlation_id

        response = await call_next(request)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds baseline security headers to every response."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith(_NO_STORE_PATH_PREFIX):
            response.headers["Cache-Control"] = "no-store"
        return response


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or "unknown"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs method/path/status/duration/correlation-id - never headers or
    bodies - and, when `app.state.metrics` is present (Phase 11), records
    `finquest_http_requests_total`/`_duration_seconds`/`_in_progress` using
    the normalized route *template* (never a raw path containing an ID) as
    the label, so cardinality stays bounded."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        metrics = getattr(request.app.state, "metrics", None)
        started_at = time.perf_counter()

        response = await call_next(request)

        duration_seconds = time.perf_counter() - started_at
        duration_ms = round(duration_seconds * 1000, 2)
        correlation_id = getattr(request.state, "correlation_id", "unknown")
        logger.info(
            "%s %s -> %s (%sms) [%s]",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            correlation_id,
            extra={
                "http_method": request.method,
                "http_path": request.url.path,
                "http_status_code": response.status_code,
                "duration_ms": duration_ms,
                "correlation_id": correlation_id,
            },
        )

        if metrics is not None:
            route = _route_template(request)
            status_class = f"{response.status_code // 100}xx"
            metrics.increment_counter(
                "finquest_http_requests_total",
                labels={"method": request.method, "route": route, "status_class": status_class},
            )
            metrics.observe_histogram(
                "finquest_http_request_duration_seconds",
                duration_seconds, labels={"method": request.method, "route": route},
            )

        return response
