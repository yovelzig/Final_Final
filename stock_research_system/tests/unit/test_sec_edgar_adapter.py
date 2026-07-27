"""Unit tests for `SecEdgarAdapter` (Phase G2A1).

Every request goes through an injected `httpx.AsyncClient` built on
`httpx.MockTransport` - no real network access and no live call to SEC
EDGAR is ever made in this file. Request pacing is exercised with an
injected fake clock and a recording (non-sleeping) `sleep` so tests never
wait in real time.
"""

from __future__ import annotations

import asyncio
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
from stock_research_core.application.live_research.provider_models import SecCompanyFactsRequest, SecSubmissionsRequest
from stock_research_core.domain.live_research.enums import EvidenceClassification, SourceType
from stock_research_core.infrastructure.live_research.sec_edgar_adapter import SecEdgarAdapter

_USER_AGENT = "FinQuest Research research@example.com"


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


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value


def _make_adapter(client: httpx.AsyncClient, **overrides: object) -> SecEdgarAdapter:
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    clock = _FakeClock()
    kwargs: dict[str, object] = {
        "base_url": "https://data.sec.gov",
        "user_agent": _USER_AGENT,
        "client": client,
        "clock": clock,
        "sleep": fake_sleep,
    }
    kwargs.update(overrides)
    adapter = SecEdgarAdapter(**kwargs)
    adapter._test_clock = clock  # noqa: SLF001 - test-only introspection
    adapter._test_sleep_calls = sleep_calls  # noqa: SLF001 - test-only introspection
    return adapter


_RECENT_FILINGS = {
    "accessionNumber": ["0000320193-24-000123", "0000320193-24-000100", "0000320193-23-000050"],
    "filingDate": ["2024-11-01", "2024-08-01", "2023-11-01"],
    "acceptanceDateTime": ["2024-11-01T18:00:00.000Z", "2024-08-01T18:00:00.000Z", "2023-11-01T18:00:00.000Z"],
    "form": ["10-K", "10-Q", "10-K"],
    "primaryDocument": ["aapl-20240928.htm", "aapl-20240629.htm", "aapl-20230930.htm"],
    "reportDate": ["2024-09-28", "2024-06-29", "2023-09-30"],
}


def _submissions_body(**overrides: object) -> dict:
    body = {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "filings": {"recent": dict(_RECENT_FILINGS)},
    }
    body.update(overrides)
    return body


def _company_facts_body(**overrides: object) -> dict:
    body = {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Assets": {
                    "label": "Assets",
                    "description": "Total assets.",
                    "units": {
                        "USD": [
                            {
                                "end": "2024-09-28",
                                "val": 364980000000,
                                "accn": "0000320193-24-000123",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-11-01",
                                "start": None,
                                "frame": None,
                            },
                            {
                                "end": "2023-09-30",
                                "val": 352583000000,
                                "accn": "0000320193-23-000050",
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2023-11-01",
                            },
                        ]
                    },
                }
            }
        },
    }
    body.update(overrides)
    return body


def _non_standard_json_response(body: dict) -> httpx.Response:
    """Builds a response whose body may contain non-standard JSON tokens
    (NaN, Infinity, -Infinity) that `httpx.Response(json=...)` refuses to
    encode. `json.dumps(allow_nan=True)` emits those literals directly,
    matching what a real (or malicious) upstream could send; `response.json()`
    (used by the adapter) accepts them right back via `json.loads`'s
    default `parse_constant` handling - it is the adapter's own mapping
    logic that must then reject them."""
    raw = json.dumps(body, allow_nan=True).encode("utf-8")
    return httpx.Response(200, content=raw, headers={"content-type": "application/json"})


class TestUrlsAndHeaders:
    async def test_exact_zero_padded_submissions_url(self) -> None:
        client, captured = _client_for([httpx.Response(200, json=_submissions_body())])
        adapter = _make_adapter(client)

        await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert str(captured[0].url) == "https://data.sec.gov/submissions/CIK0000320193.json"

    async def test_exact_zero_padded_companyfacts_url(self) -> None:
        client, captured = _client_for([httpx.Response(200, json=_company_facts_body())])
        adapter = _make_adapter(client)

        await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert str(captured[0].url) == "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"

    async def test_declared_user_agent_header_sent(self) -> None:
        client, captured = _client_for([httpx.Response(200, json=_submissions_body())])
        adapter = _make_adapter(client)

        await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert captured[0].headers["user-agent"] == _USER_AGENT

    async def test_no_authorization_header_sent(self) -> None:
        client, captured = _client_for([httpx.Response(200, json=_submissions_body())])
        adapter = _make_adapter(client)

        await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert "authorization" not in captured[0].headers

    async def test_accept_and_encoding_headers_sent(self) -> None:
        client, captured = _client_for([httpx.Response(200, json=_submissions_body())])
        adapter = _make_adapter(client)

        await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert captured[0].headers["accept"] == "application/json"
        assert captured[0].headers["accept-encoding"] == "gzip, deflate"


class TestSubmissionsMapping:
    async def test_official_source_classification(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_submissions_body())])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert all(c.source_type == SourceType.SEC_OFFICIAL_FILING for c in result.candidates)
        assert all(c.classification == EvidenceClassification.OFFICIAL for c in result.candidates)
        assert all(c.publisher == "U.S. Securities and Exchange Commission" for c in result.candidates)

    async def test_preserves_sec_order(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_submissions_body())])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert [c.official_identifier for c in result.candidates] == _RECENT_FILINGS["accessionNumber"]

    async def test_form_filtering(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_submissions_body())])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193", forms=["10-Q"]))

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["form"] == "10-Q"

    async def test_filing_limit_enforced(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_submissions_body())])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193", limit=2))

        assert len(result.candidates) == 2

    async def test_accession_number_filing_url_derived_correctly(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_submissions_body())])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert result.candidates[0].source_url == (
            "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"
        )

    async def test_missing_primary_document_does_not_invent_url(self) -> None:
        recent = dict(_RECENT_FILINGS)
        recent["primaryDocument"] = [None, "aapl-20240629.htm", "aapl-20230930.htm"]
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(filings={"recent": recent}))])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert result.candidates[0].source_url is None
        assert result.candidates[0].official_identifier == "0000320193-24-000123"

    async def test_acceptance_date_time_preferred_for_published_at(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_submissions_body())])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert result.candidates[0].published_at.year == 2024
        assert result.candidates[0].published_at.month == 11

    async def test_filing_date_fallback_when_acceptance_missing(self) -> None:
        recent = dict(_RECENT_FILINGS)
        recent["acceptanceDateTime"] = [None, None, None]
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(filings={"recent": recent}))])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert result.candidates[0].published_at is not None
        assert result.candidates[0].published_at.day == 1

    async def test_columnar_recent_filings_parsed_correctly(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_submissions_body())])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert len(result.candidates) == 3
        assert result.candidates[1].structured_facts["accession_number"] == "0000320193-24-000100"

    async def test_mismatched_column_lengths_rejected(self) -> None:
        recent = dict(_RECENT_FILINGS)
        recent["form"] = ["10-K", "10-Q"]  # one shorter than the other columns
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(filings={"recent": recent}))])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderResponseError):
            await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

    async def test_missing_required_column_rejected(self) -> None:
        recent = {k: v for k, v in _RECENT_FILINGS.items() if k != "form"}
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(filings={"recent": recent}))])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderResponseError):
            await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

    async def test_invalid_top_level_structure_rejected(self) -> None:
        client, _ = _client_for([httpx.Response(200, json={"cik": 320193})])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderResponseError):
            await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

    async def test_null_required_value_at_index_skips_that_row(self) -> None:
        recent = dict(_RECENT_FILINGS)
        recent["form"] = [None, "10-Q", "10-K"]
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(filings={"recent": recent}))])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert len(result.candidates) == 2


class TestSubmissionsDateFormatStrictness:
    @pytest.mark.parametrize("malformed_date", ["2024-1-1", "2024-01-1", "2024-1-01"])
    async def test_non_two_digit_month_or_day_filing_date_row_skipped(self, malformed_date: str) -> None:
        recent = dict(_RECENT_FILINGS)
        recent["filingDate"] = [malformed_date, "2024-08-01", "2023-11-01"]
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(filings={"recent": recent}))])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert len(result.candidates) == 2

    async def test_unicode_digit_filing_date_row_skipped(self) -> None:
        recent = dict(_RECENT_FILINGS)
        # "٢٠٢٤-١١-٠١" is "2024-11-01" written in Arabic-Indic digits.
        recent["filingDate"] = ["٢٠٢٤-١١-٠١", "2024-08-01", "2023-11-01"]
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(filings={"recent": recent}))])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert len(result.candidates) == 2

    async def test_impossible_calendar_filing_date_row_skipped(self) -> None:
        recent = dict(_RECENT_FILINGS)
        recent["filingDate"] = ["2024-02-30", "2024-08-01", "2023-11-01"]  # February never has 30 days
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(filings={"recent": recent}))])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert len(result.candidates) == 2

    async def test_bare_date_acceptance_date_time_is_rejected_and_falls_back_to_filing_date(self) -> None:
        recent = dict(_RECENT_FILINGS)
        # A bare date (no time component) is not a valid acceptance
        # timestamp - deliberately different from filingDate[0] so a
        # fallback to the (wrong) bare acceptance date is distinguishable
        # from a correct fallback to filingDate.
        recent["acceptanceDateTime"] = ["2024-11-20", "2024-08-01T18:00:00.000Z", "2023-11-01T18:00:00.000Z"]
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(filings={"recent": recent}))])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert len(result.candidates) == 3
        assert "acceptance_date_time" not in result.candidates[0].structured_facts
        assert result.candidates[0].published_at is not None
        assert result.candidates[0].published_at.year == 2024
        assert result.candidates[0].published_at.month == 11
        assert result.candidates[0].published_at.day == 1  # filingDate[0], not the bare acceptance date's day 20


class TestCompanyFactsMapping:
    async def test_official_source_classification(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_company_facts_body())])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert all(c.source_type == SourceType.EXCHANGE_REGULATOR_GOVERNMENT for c in result.candidates)
        assert all(c.classification == EvidenceClassification.OFFICIAL for c in result.candidates)
        assert all(c.publisher == "U.S. Securities and Exchange Commission" for c in result.candidates)

    async def test_taxonomy_and_concept_filtering(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_company_facts_body())])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(
            SecCompanyFactsRequest(cik="320193", concepts=["Assets", "Liabilities"])
        )

        assert all(c.structured_facts["concept"] == "Assets" for c in result.candidates)

    async def test_form_filtering(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_company_facts_body())])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(
            SecCompanyFactsRequest(cik="320193", concepts=["Assets"], forms=["10-Q"])
        )

        assert result.candidates == []

    async def test_newest_first_deterministic_ordering(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_company_facts_body())])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert [c.structured_facts["end"] for c in result.candidates] == ["2024-09-28", "2023-09-30"]

    async def test_max_facts_per_concept_enforced(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_company_facts_body())])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(
            SecCompanyFactsRequest(cik="320193", concepts=["Assets"], max_facts_per_concept=1)
        )

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["end"] == "2024-09-28"

    async def test_missing_value_is_not_converted_to_zero(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"].append(
            {
                "end": "2022-09-24",
                "accn": "0000320193-22-000108",
                "fy": 2022,
                "fp": "FY",
                "form": "10-K",
                "filed": "2022-10-28",
                # no "val" key at all
            }
        )
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert all(c.structured_facts["end"] != "2022-09-24" for c in result.candidates)
        assert not any(c.structured_facts["value"] == 0 for c in result.candidates)

    async def test_boolean_value_is_rejected_as_malformed(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"] = [
            {
                "end": "2024-09-28",
                "val": True,
                "accn": "0000320193-24-000123",
                "fy": 2024,
                "fp": "FY",
                "form": "10-K",
                "filed": "2024-11-01",
            }
        ]
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert result.candidates == []

    async def test_missing_end_date_observation_is_skipped(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"].append(
            {
                "val": 1,
                "accn": "0000320193-22-000108",
                "fy": 2022,
                "fp": "FY",
                "form": "10-K",
                "filed": "2022-10-28",
                # no "end" key
            }
        )
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 2  # only the two well-formed observations from the fixture

    async def test_official_identifier_is_deterministic(self) -> None:
        client, _ = _client_for(
            [httpx.Response(200, json=_company_facts_body()), httpx.Response(200, json=_company_facts_body())]
        )
        adapter = _make_adapter(client)

        result_one = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))
        result_two = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert [c.official_identifier for c in result_one.candidates] == [
            c.official_identifier for c in result_two.candidates
        ]

    async def test_structured_facts_contains_required_keys(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_company_facts_body())])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        facts = result.candidates[0].structured_facts
        for key in (
            "taxonomy",
            "concept",
            "label",
            "description",
            "unit",
            "value",
            "accession_number",
            "form",
            "fiscal_year",
            "fiscal_period",
            "filed_date",
            "start",
            "end",
            "frame",
        ):
            assert key in facts

    async def test_missing_facts_taxonomy_yields_empty_result(self) -> None:
        body = _company_facts_body(facts={"dei": {}})
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert result.candidates == []

    async def test_invalid_top_level_structure_rejected(self) -> None:
        client, _ = _client_for([httpx.Response(200, json={"cik": 320193})])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderResponseError):
            await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))


class TestRequestPacing:
    async def test_pacing_invokes_sleep_when_requests_are_too_close(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_submissions_body()), httpx.Response(200, json=_submissions_body())])
        adapter = _make_adapter(client, requests_per_second=5.0)

        await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))
        await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert adapter._test_sleep_calls == [pytest.approx(0.2)]

    async def test_pacing_does_not_sleep_when_enough_time_elapsed(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_submissions_body()), httpx.Response(200, json=_submissions_body())])
        adapter = _make_adapter(client, requests_per_second=5.0)

        await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))
        adapter._test_clock.value += 1.0
        await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert adapter._test_sleep_calls == []

    def test_requests_per_second_cannot_exceed_ten(self) -> None:
        client, _ = _client_for([])
        with pytest.raises(LiveResearchProviderConfigurationError):
            _make_adapter(client, requests_per_second=10.1)

    def test_requests_per_second_must_be_positive(self) -> None:
        client, _ = _client_for([])
        with pytest.raises(LiveResearchProviderConfigurationError):
            _make_adapter(client, requests_per_second=0)


class TestHttpFailureMapping:
    async def test_timeout_mapping(self) -> None:
        client, _ = _client_for([httpx.TimeoutException("timed out")])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderTimeoutError):
            await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

    async def test_429_mapping(self) -> None:
        client, _ = _client_for([httpx.Response(429, json={})])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderRateLimitError):
            await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

    async def test_403_mapping(self) -> None:
        client, _ = _client_for([httpx.Response(403, json={})])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderAccessError):
            await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

    async def test_5xx_mapping(self) -> None:
        client, _ = _client_for([httpx.Response(500, json={})])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderResponseError):
            await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

    async def test_invalid_json_mapping(self) -> None:
        client, _ = _client_for([httpx.Response(200, content=b"not json")])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderResponseError):
            await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))


class TestClientLifecycle:
    async def test_construction_performs_zero_requests(self) -> None:
        captured: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, json=_submissions_body())

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        SecEdgarAdapter(base_url="https://data.sec.gov", user_agent=_USER_AGENT, client=client)

        assert captured == []
        await client.aclose()

    async def test_aclose_does_not_close_an_injected_client(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_submissions_body())])
        adapter = _make_adapter(client)

        await adapter.aclose()

        assert not client.is_closed
        await client.aclose()

    async def test_aclose_closes_an_owned_client(self) -> None:
        adapter = SecEdgarAdapter(base_url="https://data.sec.gov", user_agent=_USER_AGENT)
        owned_client = adapter._client  # noqa: SLF001 - test-only introspection

        await adapter.aclose()

        assert owned_client.is_closed


class TestResponseCikIntegrity:
    async def test_submissions_matching_integer_cik_succeeds(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(cik=320193))])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert len(result.candidates) == 3

    async def test_submissions_matching_zero_padded_string_cik_succeeds(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(cik="0000320193"))])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert len(result.candidates) == 3

    async def test_submissions_missing_cik_rejected(self) -> None:
        body = _submissions_body()
        del body["cik"]
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderResponseError):
            await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

    async def test_submissions_malformed_cik_rejected(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(cik="32a193"))])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderResponseError):
            await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

    async def test_submissions_boolean_cik_rejected(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(cik=True))])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderResponseError):
            await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

    async def test_submissions_cik_mismatch_rejected(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(cik=999999))])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderResponseError):
            await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

    async def test_companyfacts_matching_integer_cik_succeeds(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_company_facts_body(cik=320193))])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 2

    async def test_companyfacts_matching_zero_padded_string_cik_succeeds(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_company_facts_body(cik="0000320193"))])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 2

    async def test_companyfacts_missing_cik_rejected(self) -> None:
        body = _company_facts_body()
        del body["cik"]
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderResponseError):
            await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

    async def test_companyfacts_malformed_cik_rejected(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_company_facts_body(cik="32a193"))])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderResponseError):
            await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

    async def test_companyfacts_boolean_cik_rejected(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_company_facts_body(cik=True))])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderResponseError):
            await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

    async def test_companyfacts_cik_mismatch_rejected(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_company_facts_body(cik=999999))])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderResponseError):
            await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

    async def test_submissions_arabic_indic_unicode_digit_cik_rejected(self) -> None:
        # "٠٠٠٠٣٢٠١٩٣" is "0000320193" written in Arabic-Indic
        # digits - str.isdigit()/int() both accept it, so only an
        # explicit ASCII [0-9] check can reject it.
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(cik="٠٠٠٠٣٢٠١٩٣"))])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderResponseError):
            await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

    async def test_companyfacts_arabic_indic_unicode_digit_cik_rejected(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_company_facts_body(cik="٠٠٠٠٣٢٠١٩٣"))])
        adapter = _make_adapter(client)

        with pytest.raises(LiveResearchProviderResponseError):
            await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))


class TestConcurrencySafePacing:
    async def test_concurrent_calls_cannot_both_pass_the_pacer_simultaneously(self) -> None:
        from stock_research_core.infrastructure.live_research.sec_edgar_adapter import _RequestPacer

        clock = _FakeClock()
        release_event = asyncio.Event()
        holder_entered = asyncio.Event()
        sleep_call_count = 0

        async def controlled_sleep(seconds: float) -> None:
            nonlocal sleep_call_count
            sleep_call_count += 1
            holder_entered.set()
            await release_event.wait()

        pacer = _RequestPacer(requests_per_second=5.0, clock=clock, sleep=controlled_sleep)
        await pacer.wait_for_slot()  # primes _last_request_at; no sleep needed yet

        async def paced_call() -> None:
            await pacer.wait_for_slot()

        task_a = asyncio.ensure_future(paced_call())
        task_b = asyncio.ensure_future(paced_call())

        await asyncio.wait_for(holder_entered.wait(), timeout=1.0)
        await asyncio.sleep(0)  # let the scheduler settle before asserting

        # Exactly one concurrent caller is inside the paced critical
        # section (holding the pacer's lock while "sleeping"); the other
        # is provably blocked on the lock, not racing past it at the same
        # instant.
        assert sleep_call_count == 1
        assert pacer._lock.locked()  # noqa: SLF001 - test-only introspection
        assert not task_a.done()
        assert not task_b.done()

        release_event.set()
        await asyncio.gather(task_a, task_b)

        assert not pacer._lock.locked()  # noqa: SLF001 - test-only introspection
        assert sleep_call_count == 2  # both callers eventually paced, strictly one at a time


class TestStrictAccessionValidation:
    async def test_valid_accession_produces_url(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_submissions_body())])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert result.candidates[0].source_url is not None

    async def test_too_short_accession_row_is_skipped(self) -> None:
        recent = dict(_RECENT_FILINGS)
        recent["accessionNumber"] = ["000032019-24-000123", "0000320193-24-000100", "0000320193-23-000050"]
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(filings={"recent": recent}))])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert len(result.candidates) == 2
        assert all(c.official_identifier != "000032019-24-000123" for c in result.candidates)

    async def test_malformed_hyphen_position_accession_row_is_skipped(self) -> None:
        recent = dict(_RECENT_FILINGS)
        recent["accessionNumber"] = ["0000320193-24-000123", "00003201932-4000100", "0000320193-23-000050"]
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(filings={"recent": recent}))])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert len(result.candidates) == 2

    async def test_alphabetic_accession_row_is_skipped(self) -> None:
        recent = dict(_RECENT_FILINGS)
        recent["accessionNumber"] = ["0000320193-24-000123", "000032019A-24-000100", "0000320193-23-000050"]
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(filings={"recent": recent}))])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert len(result.candidates) == 2

    async def test_unsafe_primary_document_does_not_produce_url_but_row_kept(self) -> None:
        recent = dict(_RECENT_FILINGS)
        recent["primaryDocument"] = ["../../etc/passwd", "aapl-20240629.htm", "aapl-20230930.htm"]
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(filings={"recent": recent}))])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert len(result.candidates) == 3
        assert result.candidates[0].source_url is None
        assert "primary_document" not in result.candidates[0].structured_facts

    async def test_oversized_primary_document_does_not_produce_url_or_structured_facts_field(self) -> None:
        recent = dict(_RECENT_FILINGS)
        recent["primaryDocument"] = ["a" * 256 + ".htm", "aapl-20240629.htm", "aapl-20230930.htm"]
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(filings={"recent": recent}))])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert len(result.candidates) == 3
        assert result.candidates[0].source_url is None
        assert "primary_document" not in result.candidates[0].structured_facts

    async def test_no_invented_url_when_accession_and_primary_document_malformed(self) -> None:
        recent = dict(_RECENT_FILINGS)
        recent["accessionNumber"] = ["bad-accession-number", "0000320193-24-000100", "0000320193-23-000050"]
        recent["primaryDocument"] = [None, "aapl-20240629.htm", "aapl-20230930.htm"]
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(filings={"recent": recent}))])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert all(c.official_identifier != "bad-accession-number" for c in result.candidates)
        assert not any(c.source_url and "bad-accession-number" in c.source_url for c in result.candidates)

    async def test_submissions_accession_prefix_differs_from_requested_cik_is_skipped(self) -> None:
        recent = dict(_RECENT_FILINGS)
        # Well-formed shape, but the CIK embedded in the accession number
        # (0000999999) does not match the requested CIK (0000320193).
        recent["accessionNumber"] = ["0000999999-24-000123", "0000320193-24-000100", "0000320193-23-000050"]
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(filings={"recent": recent}))])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert len(result.candidates) == 2
        assert all(c.official_identifier != "0000999999-24-000123" for c in result.candidates)

    async def test_submissions_unicode_digit_accession_rejected(self) -> None:
        recent = dict(_RECENT_FILINGS)
        # "٠٠٠٠٣٢٠١٩٣-24-000123" uses Arabic-Indic digits for the CIK
        # portion of an otherwise correctly shaped accession number.
        recent["accessionNumber"] = ["٠٠٠٠٣٢٠١٩٣-24-000123", "0000320193-24-000100", "0000320193-23-000050"]
        client, _ = _client_for([httpx.Response(200, json=_submissions_body(filings={"recent": recent}))])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert len(result.candidates) == 2


class TestCompanyFactAccessionValidation:
    async def test_accession_prefix_differs_from_requested_cik_is_skipped(self) -> None:
        body = _company_facts_body()
        # Well-formed shape, but the CIK embedded in the accession number
        # (0000999999) does not match the requested CIK (0000320193).
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["accn"] = "0000999999-24-000123"
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["end"] == "2023-09-30"

    async def test_malformed_accession_shape_is_skipped(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["accn"] = "bad-accession-number"
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["end"] == "2023-09-30"

    async def test_unicode_digit_accession_is_skipped(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["accn"] = "٠٠٠٠٣٢٠١٩٣-24-000123"
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["end"] == "2023-09-30"


class TestCompanyFactsDateValidation:
    async def test_malformed_filed_date_observation_is_skipped(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["filed"] = "not-a-date"
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["end"] == "2023-09-30"

    async def test_malformed_end_date_observation_is_skipped(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["end"] = "2024-13-40"
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["end"] == "2023-09-30"

    async def test_malformed_start_date_observation_is_skipped(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["start"] = "not-a-date"
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["end"] == "2023-09-30"

    async def test_start_later_than_end_observation_is_skipped(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["start"] = "2025-01-01"
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["end"] == "2023-09-30"

    async def test_valid_start_before_end_is_accepted(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["start"] = "2023-09-29"
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 2
        assert result.candidates[0].structured_facts["start"] == "2023-09-29"

    async def test_sort_uses_parsed_dates_not_string_tiebreak(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"].append(
            {
                "end": "2024-09-28",  # same end as the existing first entry
                "val": 111,
                "accn": "0000320193-24-000199",
                "fy": 2024,
                "fp": "Q4",
                "form": "10-K",
                "filed": "2024-11-15",  # later filed date -> must sort first
            }
        )
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert result.candidates[0].structured_facts["accession_number"] == "0000320193-24-000199"

    @pytest.mark.parametrize("malformed_end", ["2024-1-1", "2024-01-1", "2024-1-01"])
    async def test_non_two_digit_month_or_day_end_shape_rejected(self, malformed_end: str) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["end"] = malformed_end
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["end"] == "2023-09-30"

    async def test_unicode_digit_end_date_rejected(self) -> None:
        body = _company_facts_body()
        # "٢٠٢٤-٠٩-٢٨" is "2024-09-28" written in Arabic-Indic digits.
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["end"] = "٢٠٢٤-٠٩-٢٨"
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["end"] == "2023-09-30"

    async def test_impossible_calendar_date_rejected(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["end"] = "2023-02-29"  # 2023 is not a leap year
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["end"] == "2023-09-30"


class TestCompanyFactIdentityCollision:
    async def test_differing_start_produces_different_identifier(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"] = [
            {
                "end": "2024-09-28",
                "val": 100,
                "accn": "0000320193-24-000123",
                "fy": 2024,
                "fp": "Q4",
                "form": "10-K",
                "filed": "2024-11-01",
                "start": "2024-06-30",
            },
            {
                "end": "2024-09-28",
                "val": 200,
                "accn": "0000320193-24-000123",
                "fy": 2024,
                "fp": "Q4",
                "form": "10-K",
                "filed": "2024-11-01",
                "start": "2024-01-01",
            },
        ]
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 2
        identifiers = {c.official_identifier for c in result.candidates}
        assert len(identifiers) == 2

    async def test_differing_frame_produces_different_identifier(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"] = [
            {
                "end": "2024-09-28",
                "val": 100,
                "accn": "0000320193-24-000123",
                "fy": 2024,
                "fp": "Q4",
                "form": "10-K",
                "filed": "2024-11-01",
                "frame": "CY2024Q3I",
            },
            {
                "end": "2024-09-28",
                "val": 100,
                "accn": "0000320193-24-000123",
                "fy": 2024,
                "fp": "Q4",
                "form": "10-K",
                "filed": "2024-11-01",
                "frame": "CY2024Q3",
            },
        ]
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 2
        identifiers = {c.official_identifier for c in result.candidates}
        assert len(identifiers) == 2

    async def test_identifier_stays_within_two_hundred_characters(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_company_facts_body())])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert all(len(c.official_identifier) <= 200 for c in result.candidates)


class TestCompanyFactObservationIntegrity:
    async def test_nan_value_is_rejected(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["val"] = float("nan")
        client, _ = _client_for([_non_standard_json_response(body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["end"] == "2023-09-30"

    async def test_positive_infinity_value_is_rejected(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["val"] = float("inf")
        client, _ = _client_for([_non_standard_json_response(body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["end"] == "2023-09-30"

    async def test_negative_infinity_value_is_rejected(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["val"] = float("-inf")
        client, _ = _client_for([_non_standard_json_response(body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["end"] == "2023-09-30"

    async def test_ordinary_finite_int_value_is_accepted(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["val"] = 12345
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert any(c.structured_facts["value"] == 12345 for c in result.candidates)

    async def test_ordinary_finite_float_value_is_accepted(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["val"] = 123.45
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert any(c.structured_facts["value"] == 123.45 for c in result.candidates)

    async def test_blank_unit_is_rejected(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"] = {
            "   ": body["facts"]["us-gaap"]["Assets"]["units"]["USD"],
        }
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert result.candidates == []

    async def test_oversized_unit_is_rejected(self) -> None:
        body = _company_facts_body()
        oversized_unit = "U" * 51
        body["facts"]["us-gaap"]["Assets"]["units"] = {
            oversized_unit: body["facts"]["us-gaap"]["Assets"]["units"]["USD"],
        }
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert result.candidates == []

    async def test_unit_at_bound_is_accepted(self) -> None:
        body = _company_facts_body()
        bounded_unit = "U" * 50
        body["facts"]["us-gaap"]["Assets"]["units"] = {
            bounded_unit: body["facts"]["us-gaap"]["Assets"]["units"]["USD"],
        }
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 2
        assert all(c.structured_facts["unit"] == bounded_unit for c in result.candidates)

    async def test_oversized_fiscal_period_is_rejected(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["fp"] = "Q" * 21
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["end"] == "2023-09-30"

    async def test_oversized_frame_is_rejected(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["frame"] = "F" * 101
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["end"] == "2023-09-30"

    async def test_control_character_in_form_is_rejected(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["form"] = "10-K\x00"
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["end"] == "2023-09-30"

    async def test_control_character_in_unit_is_rejected(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"] = {
            "US\nD": body["facts"]["us-gaap"]["Assets"]["units"]["USD"],
        }
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert result.candidates == []

    async def test_control_character_in_fiscal_period_is_rejected(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["fp"] = "F\x01Y"
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["end"] == "2023-09-30"

    async def test_control_character_in_frame_is_rejected(self) -> None:
        body = _company_facts_body()
        body["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["frame"] = "CY2024\rQ3"
        client, _ = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert len(result.candidates) == 1
        assert result.candidates[0].structured_facts["end"] == "2023-09-30"

    async def test_value_retained_without_string_conversion(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_company_facts_body())])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert isinstance(result.candidates[0].structured_facts["value"], int)
        assert not isinstance(result.candidates[0].structured_facts["value"], str)


class TestSecProviderMetadata:
    async def test_submissions_provider_metadata(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_submissions_body())])
        adapter = _make_adapter(client)

        result = await adapter.fetch_submissions(SecSubmissionsRequest(cik="320193"))

        assert result.candidates[0].provider_metadata == {"provider": "sec_edgar", "endpoint": "submissions"}

    async def test_companyfacts_provider_metadata(self) -> None:
        client, _ = _client_for([httpx.Response(200, json=_company_facts_body())])
        adapter = _make_adapter(client)

        result = await adapter.fetch_company_facts(SecCompanyFactsRequest(cik="320193", concepts=["Assets"]))

        assert result.candidates[0].provider_metadata == {"provider": "sec_edgar", "endpoint": "companyfacts"}


class TestDefensiveConstructorValidation:
    def test_non_https_base_url_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            SecEdgarAdapter(base_url="http://data.sec.gov", user_agent=_USER_AGENT)

    def test_empty_user_agent_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            SecEdgarAdapter(base_url="https://data.sec.gov", user_agent="")

    def test_user_agent_without_contact_information_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            SecEdgarAdapter(base_url="https://data.sec.gov", user_agent="OnlyOneToken")

    def test_non_positive_timeout_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            SecEdgarAdapter(base_url="https://data.sec.gov", user_agent=_USER_AGENT, timeout_seconds=0)

    def test_non_finite_timeout_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            SecEdgarAdapter(base_url="https://data.sec.gov", user_agent=_USER_AGENT, timeout_seconds=float("nan"))

    def test_malformed_user_agent_never_appears_in_error(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError) as exc_info:
            SecEdgarAdapter(base_url="https://data.sec.gov", user_agent="OnlyOneToken")
        assert "OnlyOneToken" not in str(exc_info.value)

    def test_valid_construction_succeeds(self) -> None:
        adapter = SecEdgarAdapter(base_url="https://data.sec.gov", user_agent=_USER_AGENT)
        assert adapter.provider_name == "sec_edgar"

    def test_base_url_whitespace_is_stripped(self) -> None:
        adapter = SecEdgarAdapter(base_url="  https://data.sec.gov  ", user_agent=_USER_AGENT)
        assert adapter._base_url == "https://data.sec.gov"  # noqa: SLF001 - test-only introspection

    def test_base_url_trailing_slash_removed(self) -> None:
        adapter = SecEdgarAdapter(base_url="https://data.sec.gov/", user_agent=_USER_AGENT)
        assert adapter._base_url == "https://data.sec.gov"  # noqa: SLF001 - test-only introspection

    def test_base_url_missing_hostname_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            SecEdgarAdapter(base_url="https://", user_agent=_USER_AGENT)

    def test_base_url_with_username_password_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            SecEdgarAdapter(base_url="https://user:pass@data.sec.gov", user_agent=_USER_AGENT)

    def test_base_url_with_query_component_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            SecEdgarAdapter(base_url="https://data.sec.gov?x=1", user_agent=_USER_AGENT)

    def test_base_url_with_fragment_component_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            SecEdgarAdapter(base_url="https://data.sec.gov#frag", user_agent=_USER_AGENT)

    def test_user_agent_is_stripped_and_stored(self) -> None:
        adapter = SecEdgarAdapter(base_url="https://data.sec.gov", user_agent=f"  {_USER_AGENT}  ")
        assert adapter._user_agent == _USER_AGENT  # noqa: SLF001 - test-only introspection

    def test_oversized_user_agent_rejected(self) -> None:
        oversized = _USER_AGENT + " " + ("x" * 250)
        with pytest.raises(LiveResearchProviderConfigurationError):
            SecEdgarAdapter(base_url="https://data.sec.gov", user_agent=oversized)

    def test_user_agent_at_bound_accepted(self) -> None:
        padding = "y" * (250 - len(_USER_AGENT) - 1)
        exactly_bounded = f"{_USER_AGENT} {padding}"
        assert len(exactly_bounded) == 250
        adapter = SecEdgarAdapter(base_url="https://data.sec.gov", user_agent=exactly_bounded)
        assert adapter._user_agent == exactly_bounded  # noqa: SLF001 - test-only introspection

    def test_user_agent_with_control_character_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            SecEdgarAdapter(base_url="https://data.sec.gov", user_agent=_USER_AGENT + "\x00")

    def test_requests_per_second_bool_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            SecEdgarAdapter(base_url="https://data.sec.gov", user_agent=_USER_AGENT, requests_per_second=True)

    def test_timeout_bool_rejected(self) -> None:
        with pytest.raises(LiveResearchProviderConfigurationError):
            SecEdgarAdapter(base_url="https://data.sec.gov", user_agent=_USER_AGENT, timeout_seconds=True)
