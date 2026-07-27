"""Unit tests for the per-provider-call evidence mapping functions
(Phase G2B, corrected by G2B Correction V2 item 1).

Validation is bound to the exact provider call, not a shared global
allowlist - each of `discovery_candidate_to_evidence_kwargs`,
`sec_submissions_candidate_to_evidence_kwargs`, and
`sec_company_facts_candidate_to_evidence_kwargs` accepts *only* its own
single source_type/classification pairing and rejects every other
pairing (including the other two calls' own valid pairings) with
`LiveResearchProviderResponseError` - a provider-response integrity
failure, not a benign skip. `candidate.provider_metadata` and
`ProviderFetchResult.metadata` are excluded from the mapped kwargs by
design (neither is ever read).
"""

from __future__ import annotations

import itertools

import pytest

from stock_research_core.application.exceptions import LiveResearchProviderResponseError
from stock_research_core.application.live_research.provider_evidence_mapping import (
    discovery_candidate_to_evidence_kwargs,
    sec_company_facts_candidate_to_evidence_kwargs,
    sec_submissions_candidate_to_evidence_kwargs,
)
from stock_research_core.application.live_research.provider_models import ExternalEvidenceCandidate
from stock_research_core.domain.live_research.enums import EvidenceClassification, SourceType

_DISCOVERY_PAIR = (SourceType.DISCOVERY_ONLY, EvidenceClassification.NON_OFFICIAL)
_SUBMISSIONS_PAIR = (SourceType.SEC_OFFICIAL_FILING, EvidenceClassification.OFFICIAL)
_COMPANY_FACTS_PAIR = (SourceType.EXCHANGE_REGULATOR_GOVERNMENT, EvidenceClassification.OFFICIAL)

#: Each call's own mapping function, its one allowed pair, and the two
#: pairs that call must reject (including the *other two calls'* valid
#: pairings - a discovery result claiming SEC_OFFICIAL_FILING/OFFICIAL
#: must be rejected by the discovery mapping function, etc.).
_CALL_SPECS = [
    ("discovery", discovery_candidate_to_evidence_kwargs, _DISCOVERY_PAIR),
    ("sec_submissions", sec_submissions_candidate_to_evidence_kwargs, _SUBMISSIONS_PAIR),
    ("sec_company_facts", sec_company_facts_candidate_to_evidence_kwargs, _COMPANY_FACTS_PAIR),
]


def _candidate(source_type: SourceType, classification: EvidenceClassification) -> ExternalEvidenceCandidate:
    return ExternalEvidenceCandidate(
        source_type=source_type,
        classification=classification,
        source_url="https://example.com/filing",
        official_identifier=None,
        source_title="A Filing",
        publisher="example.com",
        published_at=None,
        raw_excerpt="Some excerpt text.",
        normalized_text=None,
        structured_facts=None,
        provider_metadata={"discovery_provider": "perplexity_search"},
    )


class TestEachCallAcceptsOnlyItsOwnPair:
    @pytest.mark.parametrize("name,mapping_fn,own_pair", _CALL_SPECS, ids=[spec[0] for spec in _CALL_SPECS])
    def test_own_pair_is_accepted(self, name, mapping_fn, own_pair) -> None:
        source_type, classification = own_pair
        candidate = _candidate(source_type, classification)
        kwargs = mapping_fn(candidate)
        assert kwargs["source_type"] == source_type
        assert kwargs["classification"] == classification


class TestDiscoveryRejectsEveryOtherPair:
    """The regression this correction exists for: a discovery result
    must never be accepted as an official SEC pairing."""

    @pytest.mark.parametrize(
        "source_type,classification",
        [pair for pair in itertools.product(SourceType, EvidenceClassification) if pair != _DISCOVERY_PAIR],
    )
    def test_disallowed_pair_raises(self, source_type: SourceType, classification: EvidenceClassification) -> None:
        candidate = _candidate(source_type, classification)
        with pytest.raises(LiveResearchProviderResponseError):
            discovery_candidate_to_evidence_kwargs(candidate)

    def test_discovery_provider_attempting_sec_official_filing_official_is_rejected(self) -> None:
        candidate = _candidate(SourceType.SEC_OFFICIAL_FILING, EvidenceClassification.OFFICIAL)
        with pytest.raises(LiveResearchProviderResponseError):
            discovery_candidate_to_evidence_kwargs(candidate)


class TestSecSubmissionsRejectsEveryOtherPair:
    @pytest.mark.parametrize(
        "source_type,classification",
        [pair for pair in itertools.product(SourceType, EvidenceClassification) if pair != _SUBMISSIONS_PAIR],
    )
    def test_disallowed_pair_raises(self, source_type: SourceType, classification: EvidenceClassification) -> None:
        candidate = _candidate(source_type, classification)
        with pytest.raises(LiveResearchProviderResponseError):
            sec_submissions_candidate_to_evidence_kwargs(candidate)

    def test_submissions_returning_the_company_facts_pair_is_rejected(self) -> None:
        candidate = _candidate(SourceType.EXCHANGE_REGULATOR_GOVERNMENT, EvidenceClassification.OFFICIAL)
        with pytest.raises(LiveResearchProviderResponseError):
            sec_submissions_candidate_to_evidence_kwargs(candidate)


class TestSecCompanyFactsRejectsEveryOtherPair:
    @pytest.mark.parametrize(
        "source_type,classification",
        [pair for pair in itertools.product(SourceType, EvidenceClassification) if pair != _COMPANY_FACTS_PAIR],
    )
    def test_disallowed_pair_raises(self, source_type: SourceType, classification: EvidenceClassification) -> None:
        candidate = _candidate(source_type, classification)
        with pytest.raises(LiveResearchProviderResponseError):
            sec_company_facts_candidate_to_evidence_kwargs(candidate)

    def test_company_facts_returning_the_submissions_pair_is_rejected(self) -> None:
        candidate = _candidate(SourceType.SEC_OFFICIAL_FILING, EvidenceClassification.OFFICIAL)
        with pytest.raises(LiveResearchProviderResponseError):
            sec_company_facts_candidate_to_evidence_kwargs(candidate)


class TestProviderMetadataExcluded:
    @pytest.mark.parametrize("name,mapping_fn,own_pair", _CALL_SPECS, ids=[spec[0] for spec in _CALL_SPECS])
    def test_candidate_provider_metadata_is_never_forwarded(self, name, mapping_fn, own_pair) -> None:
        source_type, classification = own_pair
        candidate = _candidate(source_type, classification)
        assert candidate.provider_metadata  # sanity: the candidate does carry some
        kwargs = mapping_fn(candidate)
        assert "provider_metadata" not in kwargs

    def test_mapped_kwargs_only_contain_record_evidence_accepted_fields(self) -> None:
        candidate = _candidate(*_SUBMISSIONS_PAIR)
        kwargs = sec_submissions_candidate_to_evidence_kwargs(candidate)
        assert set(kwargs) == {
            "source_type", "classification", "source_title", "publisher", "source_url",
            "official_identifier", "published_at", "raw_excerpt", "normalized_text", "structured_facts",
        }
