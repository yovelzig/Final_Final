"""Shared, provider-agnostic HTTP request execution and failure mapping
for the Live Research infrastructure adapters (Phase G2A1).

Used by both `perplexity_search_adapter` and `sec_edgar_adapter` so the
transport/HTTP-status -> exception mapping is defined exactly once. Never
retries - retry policy belongs to a later phase (G2B).
"""

from __future__ import annotations

from typing import Any

import httpx

from stock_research_core.application.exceptions import (
    LiveResearchProviderAccessError,
    LiveResearchProviderRateLimitError,
    LiveResearchProviderResponseError,
    LiveResearchProviderTimeoutError,
)

_MAX_RETRY_AFTER_SECONDS = 24 * 60 * 60  # a sane upper bound for a "safe, bounded integer" Retry-After
_MAX_SAFE_REQUEST_ID_LENGTH = 100


def _parse_retry_after_seconds(response: httpx.Response) -> int | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = int(raw.strip())
    except ValueError:
        return None
    if not (0 <= seconds <= _MAX_RETRY_AFTER_SECONDS):
        return None
    return seconds


def _safe_request_id(response: httpx.Response) -> str | None:
    value = response.headers.get("x-request-id")
    if not value:
        return None
    return value[:_MAX_SAFE_REQUEST_ID_LENGTH]


async def execute_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    provider: str,
    endpoint_category: str,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
) -> httpx.Response:
    """Executes one HTTP request and maps transport/HTTP failures onto the
    Live Research provider exception hierarchy. `endpoint_category` is a
    short, safe label (e.g. `"search"`, `"submissions"`) - never a full
    URL or query string."""
    try:
        response = await client.request(method, url, headers=headers, json=json_body)
    except httpx.TimeoutException as exc:
        raise LiveResearchProviderTimeoutError(
            f"{provider}: request to {endpoint_category} timed out"
        ) from exc
    except httpx.TransportError as exc:
        raise LiveResearchProviderResponseError(
            f"{provider}: request to {endpoint_category} failed at the transport layer"
        ) from exc

    if response.status_code == 429:
        request_id = _safe_request_id(response)
        suffix = f" (request id {request_id})" if request_id else ""
        raise LiveResearchProviderRateLimitError(
            f"{provider}: {endpoint_category} responded HTTP 429{suffix}",
            retry_after_seconds=_parse_retry_after_seconds(response),
        )
    if response.status_code in (401, 403):
        raise LiveResearchProviderAccessError(
            f"{provider}: {endpoint_category} responded HTTP {response.status_code}"
        )
    if response.status_code >= 400:
        raise LiveResearchProviderResponseError(
            f"{provider}: {endpoint_category} responded HTTP {response.status_code}"
        )
    return response


def parse_json_body(response: httpx.Response, *, provider: str, endpoint_category: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise LiveResearchProviderResponseError(
            f"{provider}: {endpoint_category} returned a non-JSON response"
        ) from exc
