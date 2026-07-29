"""Company/ticker -> SEC CIK resolution (spec G2D2/H1 correction pass,
section 5): the only authoritative source `request_live_research` may
take a `sec_cik` value from for a FINANCIAL_FILING_REVIEW/COMPANY_OVERVIEW
request - never fabricated, never guessed, never silently downgraded to
NEWS_SCAN when resolution fails.

A distinct concern from `contracts.ports.SecurityResolverPort`, which
resolves market-data securities (ticker/exchange/currency) and has no
notion of a SEC CIK at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class CikResolutionStatus(StrEnum):
    RESOLVED = "RESOLVED"
    #: More than one company matched the given name - never guessed at,
    #: always surfaced as a bounded clarification request.
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True)
class CikResolutionResult:
    status: CikResolutionStatus
    #: Set only when `status == RESOLVED`. Always sourced from the
    #: resolver's own authoritative data - never derived from
    #: `learner`-supplied text directly.
    cik: str | None = None
    company_name: str | None = None


class CikResolverPort(Protocol):
    """Checked by `request_live_research` before a FINANCIAL_FILING_
    REVIEW/COMPANY_OVERVIEW job is ever created. Exactly one of `ticker`/
    `company_name` is expected to be provided by the caller."""

    async def resolve(self, *, ticker: str | None, company_name: str | None) -> CikResolutionResult: ...
