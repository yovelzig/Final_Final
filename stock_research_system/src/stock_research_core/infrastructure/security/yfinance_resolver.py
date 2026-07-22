"""yfinance-backed implementation of `SecurityResolverPort`.

This is the only place in the codebase allowed to know that "yfinance"
is the current market-data provider. It turns a ticker or company name
into a validated `Security` domain object; nothing outside this module
should ever see a raw yfinance response.
"""

from __future__ import annotations

import asyncio
from typing import Any

import yfinance as yf

from stock_research_core.application.exceptions import (
    AmbiguousSecurityError,
    InvalidSecurityQueryError,
    ProviderRequestError,
    SecurityNotFoundError,
)
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.models import Security

_EXCHANGE_MAP: dict[str, Exchange] = {
    "NASDAQ": Exchange.NASDAQ,
    "NMS": Exchange.NASDAQ,
    "NGM": Exchange.NASDAQ,
    "NCM": Exchange.NASDAQ,
    "NYSE": Exchange.NYSE,
    "NYQ": Exchange.NYSE,
    "AMEX": Exchange.AMEX,
    "ASE": Exchange.AMEX,
}

_EXCLUDED_QUOTE_TYPES = {"CRYPTOCURRENCY", "FUTURE", "CURRENCY", "MUTUALFUND", "INDEX"}


def _map_exchange(raw_exchange: str | None) -> Exchange:
    """Map a provider-specific exchange code onto the domain `Exchange` enum."""
    if not raw_exchange:
        return Exchange.OTHER
    return _EXCHANGE_MAP.get(raw_exchange.strip().upper(), Exchange.OTHER)


class YFinanceSecurityResolver:
    """Resolves a ticker or company name to a `Security` via yfinance."""

    async def resolve(self, ticker: str | None, company_name: str | None) -> Security:
        normalized_ticker = ticker.strip().upper() if ticker and ticker.strip() else None
        normalized_name = company_name.strip() if company_name and company_name.strip() else None

        if not normalized_ticker and not normalized_name:
            raise InvalidSecurityQueryError(
                "Either a ticker or a company name must be supplied to resolve a security."
            )

        if normalized_ticker:
            return await self._resolve_by_ticker(normalized_ticker)

        assert normalized_name is not None
        return await self._resolve_by_company_name(normalized_name)

    async def _resolve_by_ticker(self, ticker: str) -> Security:
        try:
            info, history = await asyncio.to_thread(self._fetch_ticker_data, ticker)
        except Exception as exc:  # noqa: BLE001 - isolate provider failures
            raise ProviderRequestError(
                f"yfinance request failed while resolving ticker '{ticker}'."
            ) from exc

        if history is None or history.empty:
            raise SecurityNotFoundError(
                f"No tradable security with recent historical prices was found for ticker '{ticker}'."
            )

        return self._build_security(ticker, info)

    @staticmethod
    def _fetch_ticker_data(ticker: str) -> tuple[dict[str, Any], Any]:
        yf_ticker = yf.Ticker(ticker)
        info = yf_ticker.info or {}
        history = yf_ticker.history(period="5d")
        return info, history

    @staticmethod
    def _build_security(ticker: str, info: dict[str, Any]) -> Security:
        company_name = info.get("longName") or info.get("shortName") or ticker
        currency = str(info.get("currency") or "USD").upper()
        exchange = _map_exchange(info.get("exchange"))
        sector = info.get("sector") or None
        industry = info.get("industry") or None

        return Security(
            ticker=ticker,
            company_name=company_name,
            exchange=exchange,
            currency=currency,
            sector=sector,
            industry=industry,
        )

    async def _resolve_by_company_name(self, company_name: str) -> Security:
        try:
            results = await asyncio.to_thread(self._search_company, company_name)
        except Exception as exc:  # noqa: BLE001 - isolate provider failures
            raise ProviderRequestError(
                f"yfinance search failed for company name '{company_name}'."
            ) from exc

        candidates = [quote for quote in results if self._is_plausible_equity(quote)]
        if not candidates:
            raise SecurityNotFoundError(
                f"No plausible tradable security was found for company name '{company_name}'."
            )

        best_match = self._select_best_match(company_name, candidates)
        ticker = str(best_match.get("symbol") or "").strip().upper()
        if not ticker:
            raise SecurityNotFoundError(
                f"No plausible tradable security was found for company name '{company_name}'."
            )

        return await self._resolve_by_ticker(ticker)

    @staticmethod
    def _search_company(company_name: str) -> list[dict[str, Any]]:
        search = yf.Search(company_name, max_results=10)
        return list(getattr(search, "quotes", None) or [])

    @staticmethod
    def _is_plausible_equity(quote: dict[str, Any]) -> bool:
        quote_type = str(quote.get("quoteType", "")).upper()
        if quote_type in _EXCLUDED_QUOTE_TYPES:
            return False
        if quote_type and quote_type != "EQUITY":
            return False
        return bool(quote.get("symbol"))

    @staticmethod
    def _select_best_match(
        company_name: str, candidates: list[dict[str, Any]]
    ) -> dict[str, Any]:
        normalized_query = company_name.strip().casefold()

        exact_matches = [
            quote
            for quote in candidates
            if str(quote.get("longname", "")).casefold() == normalized_query
            or str(quote.get("shortname", "")).casefold() == normalized_query
        ]
        pool = exact_matches or candidates

        us_listed = [
            quote for quote in pool if str(quote.get("exchange", "")).upper() in _EXCHANGE_MAP
        ]
        if us_listed:
            pool = us_listed

        if len(pool) > 1:
            symbols = sorted({str(quote.get("symbol")) for quote in pool})
            raise AmbiguousSecurityError(
                f"Multiple plausible securities were found for company name "
                f"'{company_name}': {', '.join(symbols)}."
            )

        return pool[0]
