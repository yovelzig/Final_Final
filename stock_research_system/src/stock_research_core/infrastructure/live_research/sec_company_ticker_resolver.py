"""`SecCompanyTickerResolver`: resolves a ticker/company name to an
authoritative SEC CIK via SEC EDGAR's public, unauthenticated
`company_tickers.json` mapping (spec G2D2/H1 correction pass, section 5) -
the same "declared User-Agent, no API key" access pattern
`SecEdgarAdapter` already uses for its own SEC EDGAR calls.

Fetched once and cached in memory for this adapter instance's lifetime -
never re-fetched per request. Never fabricates or guesses a CIK: a
company name matching zero or more than one entry is reported back as
`NOT_FOUND`/`AMBIGUOUS`, never silently resolved to the "closest"
candidate.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from stock_research_core.application.live_research.cik_resolver_ports import (
    CikResolutionResult,
    CikResolutionStatus,
)

_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


class SecCompanyTickerResolver:
    def __init__(
        self, *, user_agent: str, client: httpx.AsyncClient | None = None, timeout_seconds: float = 10.0,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._user_agent = user_agent
        #: ticker (upper) -> (cik, title)
        self._by_ticker: dict[str, tuple[str, str]] | None = None
        self._entries: list[tuple[str, str, str]] | None = None  # (ticker, cik, title)
        self._load_lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _ensure_loaded(self) -> None:
        if self._by_ticker is not None:
            return
        async with self._load_lock:
            if self._by_ticker is not None:
                return
            response = await self._client.get(_COMPANY_TICKERS_URL, headers={"User-Agent": self._user_agent})
            response.raise_for_status()
            payload: dict[str, Any] = response.json()

            by_ticker: dict[str, tuple[str, str]] = {}
            entries: list[tuple[str, str, str]] = []
            for row in payload.values():
                ticker = str(row.get("ticker", "")).strip().upper()
                raw_cik = str(row.get("cik_str", "")).strip()
                title = str(row.get("title", "")).strip()
                if not ticker or not raw_cik.isdigit() or not title:
                    continue
                cik = raw_cik.lstrip("0") or "0"
                by_ticker[ticker] = (cik, title)
                entries.append((ticker, cik, title))

            self._by_ticker = by_ticker
            self._entries = entries

    async def resolve(self, *, ticker: str | None, company_name: str | None) -> CikResolutionResult:
        await self._ensure_loaded()
        assert self._by_ticker is not None
        assert self._entries is not None

        if ticker:
            match = self._by_ticker.get(ticker.strip().upper())
            if match is None:
                return CikResolutionResult(status=CikResolutionStatus.NOT_FOUND)
            cik, title = match
            return CikResolutionResult(status=CikResolutionStatus.RESOLVED, cik=cik, company_name=title)

        if company_name:
            needle = company_name.strip().lower()
            if not needle:
                return CikResolutionResult(status=CikResolutionStatus.NOT_FOUND)

            exact = {(cik, title) for _, cik, title in self._entries if title.lower() == needle}
            if len(exact) == 1:
                cik, title = next(iter(exact))
                return CikResolutionResult(status=CikResolutionStatus.RESOLVED, cik=cik, company_name=title)
            if len(exact) > 1:
                return CikResolutionResult(status=CikResolutionStatus.AMBIGUOUS)

            partial = {(cik, title) for _, cik, title in self._entries if needle in title.lower()}
            if len(partial) == 1:
                cik, title = next(iter(partial))
                return CikResolutionResult(status=CikResolutionStatus.RESOLVED, cik=cik, company_name=title)
            if len(partial) > 1:
                return CikResolutionResult(status=CikResolutionStatus.AMBIGUOUS)

            return CikResolutionResult(status=CikResolutionStatus.NOT_FOUND)

        return CikResolutionResult(status=CikResolutionStatus.NOT_FOUND)
