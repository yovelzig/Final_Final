"""Unit tests for `PerplexitySearchAdapter` (Phase G2A1).

Every request goes through an injected `httpx.AsyncClient` built on
`httpx.MockTransport` - no real network access and no live call to
Perplexity is ever made in this file.
"""

from __future__ import annotations

import json

import httpx
import pytest

from stock_research_core.application.exceptions import (
    LiveResearchProviderAccessError,
    LiveResearchProviderConfigurationError,
    LiveResearchProviderRateLimitError,
    LiveResearchProviderResponseError,
    LiveResearchProviderTimeoutError,
)
from stock_research_core.application.live_research.provider_models import DiscoverySearchRequest
from stock_research_core.domain.live_research.enums import EvidenceClassification, SourceType
from stock_research_core.infrastructure.live_research.perplexity_search_adapter import PerplexitySearchAdapter

_FAKE_API_KEY = "pplx-test-only-not-a-real-secret-abc123"


def _client_for(responses: list) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    captured: list[httpx.Request] = []
    state = {"index": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        index = state["index"]
        state["index"] += 1
        result = responses[index]
        if isinstance(result, Exception):
            raise result
        return result

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client, captured


def _make_adapter(client: httpx.AsyncClient, **overrides: object) -> PerplexitySearchAdapter:
    kwargs = {"base_url": "https://api.perplexity.ai", "api_key": _FAKE_API_KEY, "client": client}
    kwargs.update(overrides)
    return PerplexitySearchAdapter(**kwargs)


def _search_response(results: list[dict] | None = None, **extra: object) -> httpx.Response:
    body = {
        "results": results if results is not None else [],
        "id": "req-123",
        "server_time": "2026-01-01T00:00:00Z",
    }
    body.update(extra)
    return httpx.Response(200, json=body)


_ONE_RESULT = {
    "title": "Apple reports Q3 earnings",
    "url": "https://www.reuters.com/business/apple-q3",
    "snippet": "Apple reported record revenue.",
    "date": "2026-01-01",
    "last_updated": "2026-01-02",
}


class TestRequestShape:
    async def test_correct_endpoint(self) -> None:
        client, captured = _client_for([_search_response()])
        adapter = _make_adapter(client)

        await adapter.search(DiscoverySearchRequest(query="Apple earnings"))

        assert str(captured[0].url) == "https://api.perplexity.ai/search"

    async def test_correct_bearer_authorization_header(self) -> None:
        client, captured = _client_for([_search_response()])
        adapter = _make_adapter(client)

        await adapter.search(DiscoverySearchRequest(query="Apple earnings"))

        assert captured[0].headers["authorization"] == f"Bearer {_FAKE_API_KEY}"

    async def test_no_model_field_in_payload(self) -> None:
        client, captured = _client_for([_search_response()])
        adapter = _make_adapter(client)

        await adapter.search(DiscoverySearchRequest(query="Apple earnings"))

        payload = json.loads(captured[0].content)
        assert "model" not in payload

    async def test_no_messages_field_in_payload(self) -> None:
        client, captured = _client_for([_search_response()])
        adapter = _make_adapter(client)

        await adapter.search(DiscoverySearchRequest(query="Apple earnings"))

        payload = json.loads(captured[0].content)
        assert "messages" not in payload

    async def test_only_supported_request_keys_present(self) -> None:
        client, captured = _client_for([_search_response()])
        adapter = _make_adapter(client)

        await adapter.search(
            DiscoverySearchRequest(
                query="Apple earnings",
                country="us",
                language_filters=["en"],
                domain_filters=["reuters.com"],
                recency="week",
            )
        )

        payload = json.loads(captured[0].content)
        assert set(payload.keys()) == {
            "query",
            "max_results",
            "max_tokens",
            "max_tokens_per_page",
            "country",
            "search_language_filter",
            "search_domain_filter",
            "search_recency_filter",
        }

    async def test_optional_filters_mapped_correctly(self) -> None:
        client, captured = _client_for([_search_response()])
        adapter = _make_adapter(client)

        await adapter.search(
            DiscoverySearchRequest(
                query="Apple earnings",
                country="us",
                language_filters=["en"],
                domain_filters=["reuters.com"],
                recency="week",
            )
        )

        payload = json.loads(captured[0].content)
        assert payload["country"] == "US"
        assert payload["search_language_filter"] == ["en"]
        assert payload["search_domain_filter"] == ["reuters.com"]
        assert payload["search_recency_filter"] == "week"

    async def test_optional_filters_absent_when_not_supplied(self) -> None:
        client, captured = _client_for([_search_response()])
        adapter = _make_adapter(client)

        await adapter.search(DiscoverySearchRequest(query="Apple earnings"))

        payload = json.loads(captured[0].content)
        for key in ("country", "search_language_filter", "search_domain_filter", "search_recency_filter"):
            assert key not in payload

    async def test_base_url_rstrips_trailing_slash(self) -> None:
        client, captured = _client_for([_search_response()])
        adapter = _make_adapter(client, base_url="https://api.perplexity.ai/")

        await adapter.search(DiscoverySearchRequest(query="Apple earnings"))

        assert str(captured[0].url) == "https://api.perplexity.ai/search"


class TestResponseMapping:
    async def test_response_ordering_preserved(self) -> None:
        result_a = dict(_ONE_RESULT, title="First", url="https://a.example.com")
        result_b = dict(_ONE_RESULT, title="Second", url="https://b.example.com")
        client, _ = _client_for([_search_response([result_a, result_b])])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x"))

        assert [c.source_title for c in result.candidates] == ["First", "Second"]

    async def test_hostname_publisher_mapping(self) -> None:
        client, _ = _client_for([_search_response([_ONE_RESULT])])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x"))

        assert result.candidates[0].publisher == "www.reuters.com"
        assert result.candidates[0].publisher != "Perplexity"

    async def test_discovery_only_non_official_classification(self) -> None:
        client, _ = _client_for([_search_response([_ONE_RESULT])])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x"))

        assert result.candidates[0].source_type == SourceType.DISCOVERY_ONLY
        assert result.candidates[0].classification == EvidenceClassification.NON_OFFICIAL

    async def test_optional_date_parsed_safely(self) -> None:
        client, _ = _client_for([_search_response([_ONE_RESULT])])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x"))

        assert result.candidates[0].published_at is not None
        assert result.candidates[0].published_at.year == 2026

    async def test_malformed_date_does_not_raise(self) -> None:
        bad_date_result = dict(_ONE_RESULT, date="not-a-date")
        client, _ = _client_for([_search_response([bad_date_result])])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x"))

        assert len(result.candidates) == 1
        assert result.candidates[0].published_at is None

    async def test_empty_result_list_is_a_successful_empty_result(self) -> None:
        client, _ = _client_for([_search_response([])])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x"))

        assert result.candidates == []

    async def test_invalid_url_result_is_rejected_not_raised(self) -> None:
        bad = dict(_ONE_RESULT, url="not a url")
        client, _ = _client_for([_search_response([bad, _ONE_RESULT])])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x"))

        assert len(result.candidates) == 1

    async def test_missing_title_result_is_skipped(self) -> None:
        bad = {"url": "https://example.com", "snippet": "x"}
        client, _ = _client_for([_search_response([bad])])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x"))

        assert result.candidates == []

    async def test_non_dict_result_entry_is_skipped(self) -> None:
        client, _ = _client_for([_search_response(["not-a-dict"])])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x"))

        assert result.candidates == []

    async def test_invalid_json_response_raises_response_error(self) -> None:
        bad = httpx.Response(200, content=b"not json")
        client, _ = _client_for([bad])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderResponseError):
            await adapter.search(DiscoverySearchRequest(query="x"))

    async def test_invalid_result_shape_missing_results_key_raises(self) -> None:
        client, _ = _client_for([httpx.Response(200, json={"id": "x"})])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderResponseError):
            await adapter.search(DiscoverySearchRequest(query="x"))


class TestHttpFailureMapping:
    async def test_timeout_mapping(self) -> None:
        client, _ = _client_for([httpx.TimeoutException("timed out")])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderTimeoutError):
            await adapter.search(DiscoverySearchRequest(query="x"))

    async def test_429_and_retry_after_mapping(self) -> None:
        response = httpx.Response(429, headers={"Retry-After": "30"}, json={})
        client, _ = _client_for([response])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderRateLimitError) as exc_info:
            await adapter.search(DiscoverySearchRequest(query="x"))
        assert exc_info.value.retry_after_seconds == 30

    async def test_429_without_retry_after_header(self) -> None:
        client, _ = _client_for([httpx.Response(429, json={})])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderRateLimitError) as exc_info:
            await adapter.search(DiscoverySearchRequest(query="x"))
        assert exc_info.value.retry_after_seconds is None

    async def test_401_mapping(self) -> None:
        client, _ = _client_for([httpx.Response(401, json={})])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderAccessError):
            await adapter.search(DiscoverySearchRequest(query="x"))

    async def test_403_mapping(self) -> None:
        client, _ = _client_for([httpx.Response(403, json={})])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderAccessError):
            await adapter.search(DiscoverySearchRequest(query="x"))

    async def test_5xx_mapping(self) -> None:
        client, _ = _client_for([httpx.Response(503, json={})])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderResponseError):
            await adapter.search(DiscoverySearchRequest(query="x"))


class TestSecretHygiene:
    async def test_api_key_absent_from_all_exception_strings(self) -> None:
        client, _ = _client_for([httpx.Response(401, json={})])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderAccessError) as exc_info:
            await adapter.search(DiscoverySearchRequest(query="x"))

        assert _FAKE_API_KEY not in str(exc_info.value)

    async def test_api_key_absent_after_timeout(self) -> None:
        client, _ = _client_for([httpx.TimeoutException("timed out")])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderTimeoutError) as exc_info:
            await adapter.search(DiscoverySearchRequest(query="x"))

        assert _FAKE_API_KEY not in str(exc_info.value)


class TestClientLifecycle:
    async def test_construction_performs_zero_requests(self) -> None:
        captured: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, json={"results": []})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        PerplexitySearchAdapter(base_url="https://api.perplexity.ai", api_key=_FAKE_API_KEY, client=client)

        assert captured == []
        await client.aclose()

    async def test_aclose_does_not_close_an_injected_client(self) -> None:
        client, _ = _client_for([_search_response()])
        adapter = _make_adapter(client)

        await adapter.aclose()

        assert not client.is_closed
        await client.aclose()

    async def test_aclose_closes_an_owned_client(self) -> None:
        adapter = PerplexitySearchAdapter(base_url="https://api.perplexity.ai", api_key=_FAKE_API_KEY)
        owned_client = adapter._client  # noqa: SLF001 - test-only introspection

        await adapter.aclose()

        assert owned_client.is_closed


class TestDefensiveConstructorValidation:
    def test_empty_api_key_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            PerplexitySearchAdapter(base_url="https://api.perplexity.ai", api_key="")

    def test_non_https_base_url_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            PerplexitySearchAdapter(base_url="http://api.perplexity.ai", api_key=_FAKE_API_KEY)

    def test_non_positive_timeout_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            PerplexitySearchAdapter(base_url="https://api.perplexity.ai", api_key=_FAKE_API_KEY, timeout_seconds=0)

    def test_non_finite_timeout_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            PerplexitySearchAdapter(
                base_url="https://api.perplexity.ai", api_key=_FAKE_API_KEY, timeout_seconds=float("inf")
            )

    def test_non_positive_max_tokens_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            PerplexitySearchAdapter(base_url="https://api.perplexity.ai", api_key=_FAKE_API_KEY, max_tokens=0)

    def test_max_tokens_exceeding_bound_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            PerplexitySearchAdapter(base_url="https://api.perplexity.ai", api_key=_FAKE_API_KEY, max_tokens=1_000_000)

    def test_non_positive_max_tokens_per_page_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            PerplexitySearchAdapter(
                base_url="https://api.perplexity.ai", api_key=_FAKE_API_KEY, max_tokens_per_page=0
            )

    def test_max_tokens_per_page_exceeding_bound_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            PerplexitySearchAdapter(
                base_url="https://api.perplexity.ai", api_key=_FAKE_API_KEY, max_tokens_per_page=1_000_000
            )

    def test_api_key_never_appears_in_configuration_error(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError) as exc_info:
            PerplexitySearchAdapter(base_url="http://api.perplexity.ai", api_key=_FAKE_API_KEY)
        assert _FAKE_API_KEY not in str(exc_info.value)

    def test_valid_construction_succeeds(self) -> None:
        adapter = PerplexitySearchAdapter(base_url="https://api.perplexity.ai", api_key=_FAKE_API_KEY)
        assert adapter.provider_name == "perplexity_search"

    def test_whitespace_only_api_key_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            PerplexitySearchAdapter(base_url="https://api.perplexity.ai", api_key="   ")

    def test_api_key_is_stripped_and_stored(self) -> None:
        adapter = PerplexitySearchAdapter(base_url="https://api.perplexity.ai", api_key=f"  {_FAKE_API_KEY}  ")
        assert adapter._api_key == _FAKE_API_KEY  # noqa: SLF001 - test-only introspection

    def test_base_url_whitespace_is_stripped(self) -> None:
        adapter = PerplexitySearchAdapter(base_url="  https://api.perplexity.ai  ", api_key=_FAKE_API_KEY)
        assert adapter._base_url == "https://api.perplexity.ai"  # noqa: SLF001 - test-only introspection

    def test_base_url_missing_hostname_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            PerplexitySearchAdapter(base_url="https://", api_key=_FAKE_API_KEY)

    def test_base_url_with_username_password_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            PerplexitySearchAdapter(base_url="https://user:pass@api.perplexity.ai", api_key=_FAKE_API_KEY)

    def test_base_url_with_query_component_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            PerplexitySearchAdapter(base_url="https://api.perplexity.ai?x=1", api_key=_FAKE_API_KEY)

    def test_base_url_with_fragment_component_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            PerplexitySearchAdapter(base_url="https://api.perplexity.ai#frag", api_key=_FAKE_API_KEY)

    def test_max_tokens_bool_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            PerplexitySearchAdapter(base_url="https://api.perplexity.ai", api_key=_FAKE_API_KEY, max_tokens=True)

    def test_max_tokens_float_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            PerplexitySearchAdapter(base_url="https://api.perplexity.ai", api_key=_FAKE_API_KEY, max_tokens=100.0)

    def test_max_tokens_per_page_bool_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            PerplexitySearchAdapter(
                base_url="https://api.perplexity.ai", api_key=_FAKE_API_KEY, max_tokens_per_page=True
            )

    def test_max_tokens_per_page_float_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            PerplexitySearchAdapter(
                base_url="https://api.perplexity.ai", api_key=_FAKE_API_KEY, max_tokens_per_page=100.0
            )


class TestAuditMetadata:
    async def test_mixed_valid_and_invalid_results_metadata_counts(self) -> None:
        valid_result = dict(_ONE_RESULT)
        invalid_result = {"url": "https://example.com"}  # missing title
        client, _ = _client_for([_search_response([valid_result, invalid_result, valid_result])])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x"))

        assert result.metadata["raw_result_count"] == 3
        assert result.metadata["accepted_result_count"] == 2
        assert result.metadata["discarded_result_count"] == 1
        assert len(result.candidates) == 2

    async def test_empty_results_metadata_counts(self) -> None:
        client, _ = _client_for([_search_response([])])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x"))

        assert result.metadata["raw_result_count"] == 0
        assert result.metadata["accepted_result_count"] == 0
        assert result.metadata["discarded_result_count"] == 0

    async def test_accepted_ordering_preserved_with_discards_interleaved(self) -> None:
        first = dict(_ONE_RESULT, title="First", url="https://a.example.com")
        invalid = {"url": "https://example.com"}
        second = dict(_ONE_RESULT, title="Second", url="https://b.example.com")
        client, _ = _client_for([_search_response([first, invalid, second])])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x"))

        assert [c.source_title for c in result.candidates] == ["First", "Second"]

    async def test_string_provider_request_id_accepted(self) -> None:
        client, _ = _client_for([_search_response([], id="req-abc")])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x"))

        assert result.provider_request_id == "req-abc"

    async def test_integer_provider_request_id_accepted(self) -> None:
        client, _ = _client_for([_search_response([], id=12345)])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x"))

        assert result.provider_request_id == "12345"

    async def test_dict_provider_request_id_ignored(self) -> None:
        client, _ = _client_for([_search_response([], id={"nested": "value"})])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x"))

        assert result.provider_request_id is None

    async def test_list_provider_request_id_ignored(self) -> None:
        client, _ = _client_for([_search_response([], id=["a", "b"])])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x"))

        assert result.provider_request_id is None

    async def test_float_provider_request_id_ignored(self) -> None:
        client, _ = _client_for([_search_response([], id=1.5)])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x"))

        assert result.provider_request_id is None

    async def test_boolean_provider_request_id_ignored(self) -> None:
        client, _ = _client_for([_search_response([], id=True)])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x"))

        assert result.provider_request_id is None


class TestBoundedResultProcessing:
    async def test_processing_bounded_by_max_results_upstream_overflow(self) -> None:
        results = [dict(_ONE_RESULT, title=f"Result {i}", url=f"https://example{i}.com") for i in range(5)]
        client, _ = _client_for([_search_response(results)])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x", max_results=2))

        assert result.metadata["raw_result_count"] == 5
        assert result.metadata["processed_result_count"] == 2
        assert result.metadata["discarded_over_limit_count"] == 3
        assert result.metadata["accepted_result_count"] == 2
        assert result.metadata["discarded_result_count"] == 3
        assert len(result.candidates) == 2
        assert [c.source_title for c in result.candidates] == ["Result 0", "Result 1"]

    async def test_never_produces_more_candidates_than_max_results(self) -> None:
        results = [dict(_ONE_RESULT, title=f"Result {i}", url=f"https://example{i}.com") for i in range(10)]
        client, _ = _client_for([_search_response(results)])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x", max_results=3))

        assert len(result.candidates) == 3

    async def test_tail_beyond_limit_is_never_mapped_regardless_of_validity(self) -> None:
        valid = dict(_ONE_RESULT)
        malformed_beyond_limit = {"url": "https://example.com"}  # missing title - would be malformed if mapped
        results = [valid, malformed_beyond_limit]
        client, _ = _client_for([_search_response(results)])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x", max_results=1))

        assert result.metadata["raw_result_count"] == 2
        assert result.metadata["processed_result_count"] == 1
        assert result.metadata["discarded_over_limit_count"] == 1
        # The malformed entry beyond the limit is counted as over-limit,
        # never as malformed - proof it was never individually inspected.
        assert result.metadata["discarded_result_count"] == 1
        assert len(result.candidates) == 1

    async def test_accepted_ordering_preserved_when_bounded(self) -> None:
        results = [dict(_ONE_RESULT, title=f"Result {i}", url=f"https://example{i}.com") for i in range(4)]
        client, _ = _client_for([_search_response(results)])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x", max_results=3))

        assert [c.source_title for c in result.candidates] == ["Result 0", "Result 1", "Result 2"]

    async def test_within_bound_result_count_unaffected(self) -> None:
        results = [dict(_ONE_RESULT, title=f"Result {i}", url=f"https://example{i}.com") for i in range(2)]
        client, _ = _client_for([_search_response(results)])
        adapter = _make_adapter(client)

        result = await adapter.search(DiscoverySearchRequest(query="x", max_results=10))

        assert result.metadata["discarded_over_limit_count"] == 0
        assert len(result.candidates) == 2
