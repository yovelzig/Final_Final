"""Application-level provider Protocols for Live Research infrastructure
adapters (Phase G2A1).

Pure `Protocol` definitions - no `httpx`, provider SDK, or infrastructure
configuration import here. Concrete implementations (Perplexity Search,
SEC EDGAR, ...) live under `stock_research_core.infrastructure.live_research`.
Orchestration that calls these ports (background jobs, retry policy) is
out of scope for G2A1 and is added in a later phase.
"""

from __future__ import annotations

from typing import Protocol

from stock_research_core.application.live_research.provider_models import (
    DiscoverySearchRequest,
    ProviderFetchResult,
    SecCompanyFactsRequest,
    SecSubmissionsRequest,
)


class DiscoverySearchProviderPort(Protocol):
    """Discovery-only search (e.g. Perplexity Search). Never returns an
    LLM-generated answer, a claim, or a synthesized summary - only raw,
    ranked search results mapped to `ExternalEvidenceCandidate`."""

    async def search(self, request: DiscoverySearchRequest) -> ProviderFetchResult: ...


class OfficialCompanyDataProviderPort(Protocol):
    """Official company data (e.g. SEC EDGAR public data APIs)."""

    async def fetch_submissions(self, request: SecSubmissionsRequest) -> ProviderFetchResult: ...

    async def fetch_company_facts(self, request: SecCompanyFactsRequest) -> ProviderFetchResult: ...
