"""Maps a G2A1 `ExternalEvidenceCandidate` to the keyword arguments
`ResearchRequestService.record_evidence` accepts (Phase G2B).

Corrected in G2B Correction V2: validation is bound to the *exact*
provider call that produced the candidate, not a single global
three-pair allowlist. A single shared allowlist would let, for example,
a discovery-search result masquerade as an official SEC filing - each
call site gets its own dedicated mapping function that only accepts the
one pairing that call can legitimately produce:

- `DiscoverySearchProviderPort.search`              -> `DISCOVERY_ONLY` / `NON_OFFICIAL` only
- `OfficialCompanyDataProviderPort.fetch_submissions`     -> `SEC_OFFICIAL_FILING` / `OFFICIAL` only
- `OfficialCompanyDataProviderPort.fetch_company_facts`   -> `EXCHANGE_REGULATOR_GOVERNMENT` / `OFFICIAL` only

G2A1's adapters already compute the correct pairing per endpoint - these
functions do not trust that computation blindly; each validates it as a
defense-in-depth check, bound to the specific call, before any candidate
reaches persistence. A candidate whose pairing doesn't match its own
call's expected pairing is a provider-response integrity failure, not a
benign per-candidate skip: this raises rather than silently dropping it,
so the caller can fail the `ResearchRun` and the `BackgroundJob`
non-retryably.

Never reads `candidate.provider_metadata` or a `ProviderFetchResult`'s
own `metadata` - neither is ever forwarded to `record_evidence`, which
has no parameter for either.
"""

from __future__ import annotations

from typing import Any

from stock_research_core.application.exceptions import LiveResearchProviderResponseError
from stock_research_core.application.live_research.provider_models import ExternalEvidenceCandidate
from stock_research_core.domain.live_research.enums import EvidenceClassification, SourceType


def _evidence_kwargs(candidate: ExternalEvidenceCandidate) -> dict[str, Any]:
    return {
        "source_type": candidate.source_type,
        "classification": candidate.classification,
        "source_title": candidate.source_title,
        "publisher": candidate.publisher,
        "source_url": candidate.source_url,
        "official_identifier": candidate.official_identifier,
        "published_at": candidate.published_at,
        "raw_excerpt": candidate.raw_excerpt,
        "normalized_text": candidate.normalized_text,
        "structured_facts": candidate.structured_facts,
    }


def _validate_exact_pair(
    candidate: ExternalEvidenceCandidate,
    *,
    expected_source_type: SourceType,
    expected_classification: EvidenceClassification,
    provider_call: str,
) -> None:
    if candidate.source_type != expected_source_type or candidate.classification != expected_classification:
        raise LiveResearchProviderResponseError(
            f"{provider_call} returned a disallowed evidence source_type/classification pairing: "
            f"({candidate.source_type.value}, {candidate.classification.value}); "
            f"only ({expected_source_type.value}, {expected_classification.value}) is accepted from this call."
        )


def discovery_candidate_to_evidence_kwargs(candidate: ExternalEvidenceCandidate) -> dict[str, Any]:
    """For candidates from `DiscoverySearchProviderPort.search` only.
    Raises `LiveResearchProviderResponseError` for anything other than
    `DISCOVERY_ONLY`/`NON_OFFICIAL` - e.g. a discovery result that
    claims to be an official SEC pairing is rejected here, not accepted."""
    _validate_exact_pair(
        candidate, expected_source_type=SourceType.DISCOVERY_ONLY,
        expected_classification=EvidenceClassification.NON_OFFICIAL,
        provider_call="DiscoverySearchProviderPort.search",
    )
    return _evidence_kwargs(candidate)


def sec_submissions_candidate_to_evidence_kwargs(candidate: ExternalEvidenceCandidate) -> dict[str, Any]:
    """For candidates from `OfficialCompanyDataProviderPort.fetch_submissions`
    only. Raises `LiveResearchProviderResponseError` for anything other
    than `SEC_OFFICIAL_FILING`/`OFFICIAL` - e.g. a submissions result
    that carries the company-facts pairing is rejected here."""
    _validate_exact_pair(
        candidate, expected_source_type=SourceType.SEC_OFFICIAL_FILING,
        expected_classification=EvidenceClassification.OFFICIAL,
        provider_call="OfficialCompanyDataProviderPort.fetch_submissions",
    )
    return _evidence_kwargs(candidate)


def sec_company_facts_candidate_to_evidence_kwargs(candidate: ExternalEvidenceCandidate) -> dict[str, Any]:
    """For candidates from `OfficialCompanyDataProviderPort.fetch_company_facts`
    only. Raises `LiveResearchProviderResponseError` for anything other
    than `EXCHANGE_REGULATOR_GOVERNMENT`/`OFFICIAL` - e.g. a company-facts
    result that carries the submissions pairing is rejected here."""
    _validate_exact_pair(
        candidate, expected_source_type=SourceType.EXCHANGE_REGULATOR_GOVERNMENT,
        expected_classification=EvidenceClassification.OFFICIAL,
        provider_call="OfficialCompanyDataProviderPort.fetch_company_facts",
    )
    return _evidence_kwargs(candidate)
