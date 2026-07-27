"""Unit tests for the Phase G2A1 Live Research provider-neutral request and
result models (`application.live_research.provider_models`). Pure Pydantic
validation - no network access anywhere in this file.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from stock_research_core.application.live_research.provider_models import (
    DiscoverySearchRequest,
    DiscoveryRecency,
    ExternalEvidenceCandidate,
    ProviderFetchResult,
    SecCompanyFactsRequest,
    SecSubmissionsRequest,
)
from stock_research_core.domain.live_research.enums import EvidenceClassification, SourceType

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class TestDiscoverySearchRequest:
    def test_query_whitespace_is_stripped(self) -> None:
        request = DiscoverySearchRequest(query="  Apple Q3 earnings  ")
        assert request.query == "Apple Q3 earnings"

    def test_blank_query_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DiscoverySearchRequest(query="   ")

    def test_empty_query_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DiscoverySearchRequest(query="")

    def test_max_results_default(self) -> None:
        assert DiscoverySearchRequest(query="x").max_results == 10

    @pytest.mark.parametrize("value", [1, 20])
    def test_max_results_bounds_accepted(self, value: int) -> None:
        assert DiscoverySearchRequest(query="x", max_results=value).max_results == value

    @pytest.mark.parametrize("value", [0, 21, -1])
    def test_max_results_bounds_rejected(self, value: int) -> None:
        with pytest.raises(ValidationError):
            DiscoverySearchRequest(query="x", max_results=value)

    def test_country_normalized_uppercase(self) -> None:
        assert DiscoverySearchRequest(query="x", country="us").country == "US"

    def test_country_invalid_iso_alpha2_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DiscoverySearchRequest(query="x", country="USA")

    def test_language_filters_normalized_lowercase(self) -> None:
        request = DiscoverySearchRequest(query="x", language_filters=["EN", "FR"])
        assert request.language_filters == ["en", "fr"]

    def test_language_filters_invalid_entry_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DiscoverySearchRequest(query="x", language_filters=["english"])

    def test_language_filters_max_count_enforced(self) -> None:
        with pytest.raises(ValidationError):
            DiscoverySearchRequest(query="x", language_filters=["en"] * 11)

    def test_language_filters_duplicate_after_normalization_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DiscoverySearchRequest(query="x", language_filters=["EN", "en"])

    def test_domain_filters_max_count_enforced(self) -> None:
        with pytest.raises(ValidationError):
            DiscoverySearchRequest(query="x", domain_filters=[f"d{i}.com" for i in range(21)])

    def test_domain_filters_duplicate_after_normalization_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DiscoverySearchRequest(query="x", domain_filters=["Example.com", "example.com"])

    def test_domain_filters_allowlist_only_accepted(self) -> None:
        request = DiscoverySearchRequest(query="x", domain_filters=["sec.gov", "reuters.com"])
        assert request.domain_filters == ["sec.gov", "reuters.com"]

    def test_domain_filters_denylist_only_accepted(self) -> None:
        request = DiscoverySearchRequest(query="x", domain_filters=["-spam.com"])
        assert request.domain_filters == ["-spam.com"]

    def test_domain_filters_mixed_allow_and_deny_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DiscoverySearchRequest(query="x", domain_filters=["sec.gov", "-spam.com"])

    def test_recency_accepts_closed_enum_values(self) -> None:
        request = DiscoverySearchRequest(query="x", recency="week")
        assert request.recency == DiscoveryRecency.WEEK

    def test_recency_rejects_unsupported_value(self) -> None:
        with pytest.raises(ValidationError):
            DiscoverySearchRequest(query="x", recency="fortnight")

    def test_query_max_length_enforced(self) -> None:
        with pytest.raises(ValidationError):
            DiscoverySearchRequest(query="x" * 2001)


class TestSecSubmissionsRequest:
    def test_cik_normalized_to_ten_digits(self) -> None:
        assert SecSubmissionsRequest(cik="320193").cik == "0000320193"

    def test_cik_already_ten_digits_unchanged(self) -> None:
        assert SecSubmissionsRequest(cik="0000320193").cik == "0000320193"

    def test_cik_single_digit_normalized(self) -> None:
        assert SecSubmissionsRequest(cik="1").cik == "0000000001"

    def test_cik_non_digit_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SecSubmissionsRequest(cik="32a193")

    def test_cik_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SecSubmissionsRequest(cik="12345678901")

    def test_cik_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SecSubmissionsRequest(cik="")

    def test_cik_all_zero_short_form_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SecSubmissionsRequest(cik="0")

    def test_cik_all_zero_ten_digit_form_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SecSubmissionsRequest(cik="0000000000")

    def test_cik_arabic_indic_unicode_digits_rejected(self) -> None:
        # "٣٢٠١٩٣" is "320193" written in
        # Arabic-Indic digits - str.isdigit()/int() both accept it, so
        # only an explicit ASCII [0-9] check (not \d or .isdigit()) can
        # reject it.
        with pytest.raises(ValidationError):
            SecSubmissionsRequest(cik="٣٢٠١٩٣")

    def test_forms_normalized_uppercase_and_deduplicated(self) -> None:
        request = SecSubmissionsRequest(cik="1", forms=["10-k", "10-K", "8-k"])
        assert request.forms == ["10-K", "8-K"]

    def test_forms_none_by_default(self) -> None:
        assert SecSubmissionsRequest(cik="1").forms is None

    def test_limit_bounds_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SecSubmissionsRequest(cik="1", limit=201)
        with pytest.raises(ValidationError):
            SecSubmissionsRequest(cik="1", limit=0)

    def test_limit_max_accepted(self) -> None:
        assert SecSubmissionsRequest(cik="1", limit=200).limit == 200


class TestSecCompanyFactsRequest:
    def test_cik_normalized(self) -> None:
        assert SecCompanyFactsRequest(cik="320193", concepts=["Assets"]).cik == "0000320193"

    def test_cik_all_zero_short_form_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SecCompanyFactsRequest(cik="0", concepts=["Assets"])

    def test_cik_all_zero_ten_digit_form_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SecCompanyFactsRequest(cik="0000000000", concepts=["Assets"])

    def test_cik_arabic_indic_unicode_digits_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SecCompanyFactsRequest(cik="٣٢٠١٩٣", concepts=["Assets"])

    def test_taxonomy_default(self) -> None:
        assert SecCompanyFactsRequest(cik="1", concepts=["Assets"]).taxonomy == "us-gaap"

    def test_concepts_required(self) -> None:
        with pytest.raises(ValidationError):
            SecCompanyFactsRequest(cik="1", concepts=[])

    def test_concepts_deduplicated_preserving_order(self) -> None:
        request = SecCompanyFactsRequest(cik="1", concepts=["Assets", "Liabilities", "Assets"])
        assert request.concepts == ["Assets", "Liabilities"]

    def test_concepts_max_count_enforced(self) -> None:
        with pytest.raises(ValidationError):
            SecCompanyFactsRequest(cik="1", concepts=[f"Concept{i}" for i in range(51)])

    def test_concepts_blank_entry_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SecCompanyFactsRequest(cik="1", concepts=["Assets", "   "])

    def test_forms_default(self) -> None:
        request = SecCompanyFactsRequest(cik="1", concepts=["Assets"])
        assert request.forms == ["10-K", "10-Q"]

    def test_forms_normalized_and_deduplicated(self) -> None:
        request = SecCompanyFactsRequest(cik="1", concepts=["Assets"], forms=["10-q", "10-Q", "8-k"])
        assert request.forms == ["10-Q", "8-K"]

    def test_max_facts_per_concept_bounds(self) -> None:
        assert SecCompanyFactsRequest(cik="1", concepts=["Assets"], max_facts_per_concept=1).max_facts_per_concept == 1
        assert SecCompanyFactsRequest(cik="1", concepts=["Assets"], max_facts_per_concept=100).max_facts_per_concept == 100
        with pytest.raises(ValidationError):
            SecCompanyFactsRequest(cik="1", concepts=["Assets"], max_facts_per_concept=0)
        with pytest.raises(ValidationError):
            SecCompanyFactsRequest(cik="1", concepts=["Assets"], max_facts_per_concept=101)


class TestExternalEvidenceCandidate:
    def _base_kwargs(self, **overrides: object) -> dict:
        kwargs = dict(
            source_type=SourceType.DISCOVERY_ONLY,
            classification=EvidenceClassification.NON_OFFICIAL,
            source_url="https://example.com/article",
            official_identifier=None,
            source_title="Title",
            publisher="example.com",
            published_at=None,
            raw_excerpt="Some excerpt.",
            normalized_text=None,
            structured_facts=None,
            provider_metadata={},
        )
        kwargs.update(overrides)
        return kwargs

    def test_valid_candidate_constructs(self) -> None:
        candidate = ExternalEvidenceCandidate(**self._base_kwargs())
        assert candidate.publisher == "example.com"

    def test_http_url_accepted(self) -> None:
        ExternalEvidenceCandidate(**self._base_kwargs(source_url="http://example.com"))

    def test_non_http_url_scheme_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExternalEvidenceCandidate(**self._base_kwargs(source_url="ftp://example.com/file"))

    def test_javascript_scheme_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExternalEvidenceCandidate(**self._base_kwargs(source_url="javascript:alert(1)"))

    def test_source_url_max_length_enforced(self) -> None:
        overlong = "https://example.com/" + ("a" * 2000)
        with pytest.raises(ValidationError):
            ExternalEvidenceCandidate(**self._base_kwargs(source_url=overlong))

    def test_official_identifier_max_length_enforced(self) -> None:
        with pytest.raises(ValidationError):
            ExternalEvidenceCandidate(**self._base_kwargs(official_identifier="a" * 201))

    def test_source_title_max_length_enforced(self) -> None:
        with pytest.raises(ValidationError):
            ExternalEvidenceCandidate(**self._base_kwargs(source_title="a" * 1001))

    def test_publisher_max_length_enforced(self) -> None:
        with pytest.raises(ValidationError):
            ExternalEvidenceCandidate(**self._base_kwargs(publisher="a" * 251))

    def test_raw_excerpt_max_length_enforced(self) -> None:
        with pytest.raises(ValidationError):
            ExternalEvidenceCandidate(**self._base_kwargs(raw_excerpt="a" * 5001))

    def test_normalized_text_max_length_enforced(self) -> None:
        with pytest.raises(ValidationError):
            ExternalEvidenceCandidate(**self._base_kwargs(normalized_text="a" * 5001))

    def test_requires_source_url_or_official_identifier(self) -> None:
        with pytest.raises(ValidationError):
            ExternalEvidenceCandidate(**self._base_kwargs(source_url=None, official_identifier=None))

    def test_official_identifier_alone_is_sufficient_identity(self) -> None:
        candidate = ExternalEvidenceCandidate(**self._base_kwargs(source_url=None, official_identifier="0000320193-24-000123"))
        assert candidate.source_url is None

    def test_requires_excerpt_or_structured_facts(self) -> None:
        with pytest.raises(ValidationError):
            ExternalEvidenceCandidate(**self._base_kwargs(raw_excerpt=None, structured_facts=None))

    def test_structured_facts_alone_is_sufficient_payload(self) -> None:
        candidate = ExternalEvidenceCandidate(**self._base_kwargs(raw_excerpt=None, structured_facts={"value": 1}))
        assert candidate.raw_excerpt is None

    def test_structured_facts_rejects_sensitive_keys(self) -> None:
        with pytest.raises(ValidationError):
            ExternalEvidenceCandidate(**self._base_kwargs(raw_excerpt=None, structured_facts={"api_key": "secret"}))

    def test_provider_metadata_rejects_sensitive_keys(self) -> None:
        with pytest.raises(ValidationError):
            ExternalEvidenceCandidate(**self._base_kwargs(provider_metadata={"authorization": "Bearer x"}))


class TestProviderFetchResult:
    def test_empty_candidates_is_valid(self) -> None:
        result = ProviderFetchResult(provider_name="perplexity_search", fetched_at=NOW, candidates=[], metadata={})
        assert result.candidates == []

    def test_preserves_candidate_order(self) -> None:
        candidate_a = ExternalEvidenceCandidate(
            source_type=SourceType.DISCOVERY_ONLY,
            classification=EvidenceClassification.NON_OFFICIAL,
            source_url="https://a.example.com",
            source_title="A",
            publisher="a.example.com",
            raw_excerpt="a",
        )
        candidate_b = ExternalEvidenceCandidate(
            source_type=SourceType.DISCOVERY_ONLY,
            classification=EvidenceClassification.NON_OFFICIAL,
            source_url="https://b.example.com",
            source_title="B",
            publisher="b.example.com",
            raw_excerpt="b",
        )
        result = ProviderFetchResult(
            provider_name="perplexity_search", fetched_at=NOW, candidates=[candidate_a, candidate_b], metadata={}
        )
        assert result.candidates == [candidate_a, candidate_b]

    def test_metadata_rejects_sensitive_keys(self) -> None:
        with pytest.raises(ValidationError):
            ProviderFetchResult(provider_name="perplexity_search", fetched_at=NOW, metadata={"secret": "x"})
