"""Integration tests for `/api/v1/portfolios/*` against the real
PostgreSQL test database, driven over HTTP - creation, trade preview,
idempotency-key-enforced execution, holdings, journal, valuation, and
ownership.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.integration.conftest import auth_headers
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.models import MarketBar, Security

pytestmark = pytest.mark.integration

_SIM_START = datetime(2025, 1, 1, tzinfo=timezone.utc)
_TRADE_AT = datetime(2025, 1, 2, tzinfo=timezone.utc)


def _email() -> str:
    return f"portfolio-{uuid.uuid4().hex[:10]}@example.com"


async def _seed_security_with_bars(uow_factory) -> str:
    ticker = f"PF{uuid.uuid4().hex[:6].upper()}"
    async with uow_factory() as uow:
        security = await uow.securities.upsert(Security(ticker=ticker, company_name="Portfolio Co", exchange=Exchange.NASDAQ))
        bars = [
            MarketBar(
                security_id=security.security_id, timestamp=_SIM_START + timedelta(days=d),
                open=100.0 + d, high=101.0 + d, low=max(0.01, 99.0 + d), close=100.0 + d,
                adjusted_close=100.0 + d, volume=1_000_000, interval="1d", source_name="test-source",
            )
            for d in range(10)
        ]
        await uow.market_bars.upsert_many(bars)
        await uow.commit()
    return ticker


async def test_full_portfolio_trade_and_valuation_flow(api_client, uow_factory) -> None:
    ticker = await _seed_security_with_bars(uow_factory)
    headers = await auth_headers(api_client, email=_email())

    r = await api_client.post(
        "/api/v1/portfolios", headers=headers,
        json={"name": "Test Portfolio", "initial_cash": 10000.0, "simulation_start_at": _SIM_START.isoformat()},
    )
    assert r.status_code == 201
    portfolio_id = r.json()["portfolio_id"]

    r = await api_client.get("/api/v1/portfolios", headers=headers)
    assert r.status_code == 200
    assert any(p["portfolio_id"] == portfolio_id for p in r.json())

    r = await api_client.get(f"/api/v1/portfolios/{portfolio_id}", headers=headers)
    assert r.status_code == 200

    r = await api_client.post(
        f"/api/v1/portfolios/{portfolio_id}/trades/preview", headers=headers,
        json={"ticker": ticker, "transaction_type": "BUY", "quantity": 10, "requested_at": _TRADE_AT.isoformat()},
    )
    assert r.status_code == 200

    idem_key = str(uuid.uuid4())
    trade_headers = {**headers, "Idempotency-Key": idem_key}
    trade_payload = {
        "ticker": ticker, "transaction_type": "BUY", "quantity": 10, "requested_at": _TRADE_AT.isoformat(),
        "journal_entry": {
            "action": "BUY", "decision_at": _TRADE_AT.isoformat(),
            "rationale": "Diversifying after doing my own research.", "confidence": "MEDIUM",
        },
    }
    r = await api_client.post(f"/api/v1/portfolios/{portfolio_id}/trades", headers=trade_headers, json=trade_payload)
    assert r.status_code == 201
    executed = r.json()
    assert executed["transaction"]["status"] == "EXECUTED"

    # replay with the SAME idempotency key -> same transaction, not a duplicate
    r = await api_client.post(f"/api/v1/portfolios/{portfolio_id}/trades", headers=trade_headers, json=trade_payload)
    assert r.status_code == 201
    assert r.json()["transaction"]["transaction_id"] == executed["transaction"]["transaction_id"]

    r = await api_client.post(
        f"/api/v1/portfolios/{portfolio_id}/trades", headers=headers, json=trade_payload
    )
    assert r.status_code == 422  # missing Idempotency-Key header

    r = await api_client.get(f"/api/v1/portfolios/{portfolio_id}/transactions", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = await api_client.get(f"/api/v1/portfolios/{portfolio_id}/holdings", headers=headers)
    assert r.status_code == 200
    holdings = r.json()
    assert holdings[0]["quantity"] == 10.0

    r = await api_client.get(f"/api/v1/portfolios/securities/{holdings[0]['security_id']}", headers=headers)
    assert r.status_code == 200
    assert r.json()["ticker"] == ticker

    r = await api_client.get(f"/api/v1/portfolios/securities/{uuid.uuid4()}", headers=headers)
    assert r.status_code == 404

    r = await api_client.get(f"/api/v1/portfolios/{portfolio_id}/journal", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = await api_client.post(
        f"/api/v1/portfolios/{portfolio_id}/journal", headers=headers,
        json={
            "ticker": ticker, "action": "HOLD", "decision_at": _TRADE_AT.isoformat(),
            "rationale": "Holding steady, no new information changes the thesis.", "confidence": "HIGH",
        },
    )
    assert r.status_code == 201

    valuation_at = _SIM_START + timedelta(days=5)
    r = await api_client.post(
        f"/api/v1/portfolios/{portfolio_id}/valuations", headers=headers, json={"as_of": valuation_at.isoformat()}
    )
    assert r.status_code == 201
    assert r.json()["snapshot"]["total_value"] > 0

    r = await api_client.get(f"/api/v1/portfolios/{portfolio_id}/valuations/latest", headers=headers)
    assert r.status_code == 200
    assert r.json()["snapshot"] is not None


async def test_portfolio_ownership_is_enforced(api_client) -> None:
    owner_headers = await auth_headers(api_client, email=_email())
    other_headers = await auth_headers(api_client, email=_email())

    r = await api_client.post(
        "/api/v1/portfolios", headers=owner_headers,
        json={"name": "Owner's Portfolio", "initial_cash": 1000.0, "simulation_start_at": _SIM_START.isoformat()},
    )
    portfolio_id = r.json()["portfolio_id"]

    r = await api_client.get(f"/api/v1/portfolios/{portfolio_id}", headers=other_headers)
    assert r.status_code == 404

    r = await api_client.get(f"/api/v1/portfolios/{portfolio_id}/holdings", headers=other_headers)
    assert r.status_code == 404


async def test_portfolios_require_authentication(api_client) -> None:
    response = await api_client.get("/api/v1/portfolios")
    assert response.status_code == 401


async def test_performance_with_no_valuations_returns_controlled_error(api_client) -> None:
    """Phase 10 stabilization: previously a plain `ValueError` degraded to a
    generic 500; a portfolio with fewer than two valuation snapshots must
    now get a safe, actionable 422 instead."""
    headers = await auth_headers(api_client, email=_email())
    r = await api_client.post(
        "/api/v1/portfolios", headers=headers,
        json={"name": "No Valuations", "initial_cash": 1000.0, "simulation_start_at": _SIM_START.isoformat()},
    )
    portfolio_id = r.json()["portfolio_id"]

    response = await api_client.get(
        f"/api/v1/portfolios/{portfolio_id}/performance", headers=headers,
        params={"start_at": _SIM_START.isoformat(), "end_at": (_SIM_START + timedelta(days=30)).isoformat()},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INSUFFICIENT_PORTFOLIO_VALUATION_DATA"
    assert "At least two portfolio valuations" in body["error"]["message"]
    assert "correlation_id" in body["error"]
    assert "Traceback" not in response.text


async def test_performance_with_two_valuations_succeeds(api_client) -> None:
    headers = await auth_headers(api_client, email=_email())
    r = await api_client.post(
        "/api/v1/portfolios", headers=headers,
        json={"name": "Two Valuations", "initial_cash": 1000.0, "simulation_start_at": _SIM_START.isoformat()},
    )
    portfolio_id = r.json()["portfolio_id"]

    for day in (1, 5):
        r = await api_client.post(
            f"/api/v1/portfolios/{portfolio_id}/valuations", headers=headers,
            json={"as_of": (_SIM_START + timedelta(days=day)).isoformat()},
        )
        assert r.status_code == 201

    response = await api_client.get(
        f"/api/v1/portfolios/{portfolio_id}/performance", headers=headers,
        params={"start_at": _SIM_START.isoformat(), "end_at": (_SIM_START + timedelta(days=30)).isoformat()},
    )
    assert response.status_code == 200
    assert response.json()["portfolio_id"] == portfolio_id
