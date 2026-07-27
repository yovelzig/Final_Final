"""Perplexity Search API adapter (Phase G2A1), satisfying
`DiscoverySearchProviderPort`.

Calls Perplexity's discovery-only `POST {base_url}/search` endpoint
directly via `httpx` - never Sonar, `/chat/completions`, `/v1/sonar`, the
Agent API, or any model endpoint. Results are raw, ranked search hits;
this adapter never generates an answer, infers truth from ranking, or
produces a claim - it only maps each result to a `DISCOVERY_ONLY` /
`NON_OFFICIAL` `ExternalEvidenceCandidate`.

Tests must inject an `httpx.AsyncClient` built on `httpx.MockTransport` -
this adapter makes no network call during construction, and none during
the unit suite. There are no automatic retries here; retry policy belongs
to a later phase (G2B).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx

from stock_research_core.application.exceptions import (
    LiveResearchProviderConfigurationError,
    LiveResearchProviderResponseError,
)
from stock_research_core.application.live_research.provider_models import (
    DiscoverySearchRequest,
    ExternalEvidenceCandidate,
    ProviderFetchResult,
)
from stock_research_core.domain.live_research.enums import EvidenceClassification, SourceType
from stock_research_core.infrastructure.live_research._http import execute_request, parse_json_body
from stock_research_core.infrastructure.live_research.config import (
    _MAX_TOKEN_BOUND,
    _normalize_https_base_url,
    _require_finite_positive,
)

_PROVIDER_NAME = "perplexity_search"
_MAX_STRUCTURED_FIELD_LENGTH = 200
_MAX_EXCERPT_LENGTH = 5000
_MAX_PROVIDER_REQUEST_ID_LENGTH = 200


def _hostname_from_url(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        return None
    return parsed.hostname.lower()


def _bounded_provider_request_id(value: Any) -> str | None:
    """Accepts only a bounded scalar `str` or `int` for the upstream
    request id. Objects, arrays, floats, and booleans are ignored (never
    stringified) rather than trusted as an identifier."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped[:_MAX_PROVIDER_REQUEST_ID_LENGTH] if stripped else None
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)[:_MAX_PROVIDER_REQUEST_ID_LENGTH]
    return None


def _parse_published_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _map_result(raw_result: Any) -> ExternalEvidenceCandidate | None:
    """Maps one raw Perplexity search-result object to a candidate, or
    `None` if it is structurally malformed. A malformed result is
    dropped, never silently upgraded into trusted evidence."""
    if not isinstance(raw_result, dict):
        return None

    title = raw_result.get("title")
    url = raw_result.get("url")
    if not isinstance(title, str) or not title.strip():
        return None
    if not isinstance(url, str) or not url.strip():
        return None

    publisher = _hostname_from_url(url)
    if publisher is None:
        return None

    snippet = raw_result.get("snippet")
    raw_excerpt = snippet.strip()[:_MAX_EXCERPT_LENGTH] if isinstance(snippet, str) and snippet.strip() else None

    structured_facts: dict[str, Any] = {}
    last_updated = raw_result.get("last_updated")
    if isinstance(last_updated, str) and last_updated.strip():
        structured_facts["last_updated"] = last_updated.strip()[:_MAX_STRUCTURED_FIELD_LENGTH]

    try:
        return ExternalEvidenceCandidate(
            source_type=SourceType.DISCOVERY_ONLY,
            classification=EvidenceClassification.NON_OFFICIAL,
            source_url=url.strip(),
            official_identifier=None,
            source_title=title.strip()[:1000],
            publisher=publisher,
            published_at=_parse_published_at(raw_result.get("date")),
            raw_excerpt=raw_excerpt,
            normalized_text=None,
            structured_facts=structured_facts or None,
            provider_metadata={"discovery_provider": _PROVIDER_NAME},
        )
    except ValueError:
        return None


class PerplexitySearchAdapter:
    """Calls Perplexity's discovery-only Search API. Satisfies
    `DiscoverySearchProviderPort`."""

    provider_name = _PROVIDER_NAME

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 30.0,
        max_tokens: int = 10_000,
        max_tokens_per_page: int = 4_096,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        stripped_api_key = api_key.strip()
        if not stripped_api_key:
            raise LiveResearchProviderConfigurationError("perplexity_search: api_key must not be blank")
        try:
            normalized_base_url = _normalize_https_base_url("perplexity_search: base_url", base_url)
        except ValueError as exc:
            raise LiveResearchProviderConfigurationError(str(exc)) from exc
        try:
            _require_finite_positive("perplexity_search: timeout_seconds", timeout_seconds)
        except ValueError as exc:
            raise LiveResearchProviderConfigurationError(str(exc)) from exc
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int):
            raise LiveResearchProviderConfigurationError("perplexity_search: max_tokens must be an int")
        if isinstance(max_tokens_per_page, bool) or not isinstance(max_tokens_per_page, int):
            raise LiveResearchProviderConfigurationError("perplexity_search: max_tokens_per_page must be an int")
        if not (0 < max_tokens <= _MAX_TOKEN_BOUND):
            raise LiveResearchProviderConfigurationError(
                f"perplexity_search: max_tokens must be within (0, {_MAX_TOKEN_BOUND}]"
            )
        if not (0 < max_tokens_per_page <= _MAX_TOKEN_BOUND):
            raise LiveResearchProviderConfigurationError(
                f"perplexity_search: max_tokens_per_page must be within (0, {_MAX_TOKEN_BOUND}]"
            )

        self._base_url = normalized_base_url
        self._api_key = stripped_api_key
        self._max_tokens = max_tokens
        self._max_tokens_per_page = max_tokens_per_page
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def search(self, request: DiscoverySearchRequest) -> ProviderFetchResult:
        payload: dict[str, Any] = {
            "query": request.query,
            "max_results": request.max_results,
            "max_tokens": self._max_tokens,
            "max_tokens_per_page": self._max_tokens_per_page,
        }
        if request.country is not None:
            payload["country"] = request.country
        if request.language_filters:
            payload["search_language_filter"] = request.language_filters
        if request.domain_filters:
            payload["search_domain_filter"] = request.domain_filters
        if request.recency is not None:
            payload["search_recency_filter"] = request.recency.value

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        response = await execute_request(
            self._client,
            "POST",
            f"{self._base_url}/search",
            provider=_PROVIDER_NAME,
            endpoint_category="search",
            headers=headers,
            json_body=payload,
        )
        body = parse_json_body(response, provider=_PROVIDER_NAME, endpoint_category="search")

        if not isinstance(body, dict):
            raise LiveResearchProviderResponseError(f"{_PROVIDER_NAME}: search returned a non-object response body")

        raw_results = body.get("results")
        if not isinstance(raw_results, list):
            raise LiveResearchProviderResponseError(f"{_PROVIDER_NAME}: search response is missing a 'results' list")

        # Never let an upstream response override the caller's own
        # max_results - only the leading `request.max_results` raw
        # results are ever processed/mapped; the unbounded tail is never
        # iterated or inspected, regardless of whether it is malformed.
        raw_result_count = len(raw_results)
        processed_results = raw_results[: request.max_results]
        processed_result_count = len(processed_results)
        discarded_over_limit_count = raw_result_count - processed_result_count

        candidates: list[ExternalEvidenceCandidate] = []
        malformed_discarded_count = 0
        for raw_result in processed_results:
            candidate = _map_result(raw_result)
            if candidate is not None:
                candidates.append(candidate)
            else:
                malformed_discarded_count += 1

        metadata: dict[str, Any] = {
            "raw_result_count": raw_result_count,
            "processed_result_count": processed_result_count,
            "accepted_result_count": len(candidates),
            "discarded_result_count": malformed_discarded_count + discarded_over_limit_count,
            "discarded_over_limit_count": discarded_over_limit_count,
        }
        server_time = body.get("server_time")
        if isinstance(server_time, str) and server_time.strip():
            metadata["server_time"] = server_time.strip()[:_MAX_STRUCTURED_FIELD_LENGTH]

        return ProviderFetchResult(
            provider_name=_PROVIDER_NAME,
            provider_request_id=_bounded_provider_request_id(body.get("id")),
            fetched_at=datetime.now(timezone.utc),
            candidates=candidates,
            metadata=metadata,
        )
