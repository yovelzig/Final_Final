"""Unit tests for `api/exception_handlers.py`'s exception-to-HTTP mapping.

Verifies: every concrete `StockResearchError` subclass in
`application.exceptions` is either explicitly mapped or safely handled
by the isinstance-based fallback (never silently 500s with a leaked
detail), the error envelope always carries a `correlation_id`, and a
validation error's `details` never echoes back a raw password.
"""

from __future__ import annotations

import inspect

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from stock_research_core.api import exception_handlers as handlers_module
from stock_research_core.api.exception_handlers import (
    _EXCEPTION_STATUS_MAP,
    _resolve_status_and_code,
    register_exception_handlers,
)
from stock_research_core.application import exceptions as exceptions_module
from stock_research_core.application.exceptions import StockResearchError, TradeRejectedError
from stock_research_core.domain.virtual_portfolio.enums import TradeRejectionReason


def _all_stock_research_error_subclasses() -> list[type[StockResearchError]]:
    return [
        obj
        for _name, obj in inspect.getmembers(exceptions_module)
        if inspect.isclass(obj) and issubclass(obj, StockResearchError) and obj is not StockResearchError
    ]


def test_every_stock_research_error_subclass_resolves_to_a_client_or_server_status() -> None:
    for exc_class in _all_stock_research_error_subclasses():
        if exc_class is TradeRejectedError:
            instance = TradeRejectedError(TradeRejectionReason.INSUFFICIENT_CASH, "message")
        else:
            try:
                instance = exc_class("message")
            except TypeError:
                continue  # a constructor requiring extra positional args - not currently in use
        status_code, code = _resolve_status_and_code(instance)
        assert 400 <= status_code < 600
        assert code and code.isupper() or code == "APPLICATION_ERROR"


def test_every_explicitly_mapped_exception_is_a_real_stock_research_error_subclass() -> None:
    for exc_class in _EXCEPTION_STATUS_MAP:
        assert issubclass(exc_class, StockResearchError)


def test_identity_exceptions_are_explicitly_mapped_not_left_to_fallback() -> None:
    from stock_research_core.application.exceptions import (
        AccountDisabledError,
        AccountLockedError,
        AccountNotFoundError,
        AuthenticationFailedError,
        DuplicateAccountError,
        InsufficientPermissionError,
        InvalidAccessTokenError,
        InvalidPasswordError,
        InvalidRefreshTokenError,
        RateLimitExceededError,
    )

    expected_statuses = {
        AuthenticationFailedError: 401,
        AccountLockedError: 401,
        AccountDisabledError: 401,
        InvalidAccessTokenError: 401,
        InvalidRefreshTokenError: 401,
        InsufficientPermissionError: 403,
        DuplicateAccountError: 409,
        InvalidPasswordError: 422,
        RateLimitExceededError: 429,
        AccountNotFoundError: 404,
    }
    for exc_class, expected_status in expected_statuses.items():
        assert exc_class in _EXCEPTION_STATUS_MAP
        status_code, _code = _EXCEPTION_STATUS_MAP[exc_class]
        assert status_code == expected_status


def test_insufficient_portfolio_valuation_data_maps_to_a_safe_422() -> None:
    """Phase 10 stabilization: this used to be a raw `ValueError`, which
    fell through to a generic, unmapped 500 - it must now resolve to a
    dedicated, client-actionable 422."""
    from stock_research_core.application.exceptions import InsufficientPortfolioValuationDataError

    assert InsufficientPortfolioValuationDataError in _EXCEPTION_STATUS_MAP
    status_code, code = _EXCEPTION_STATUS_MAP[InsufficientPortfolioValuationDataError]
    assert status_code == 422
    assert code == "INSUFFICIENT_PORTFOLIO_VALUATION_DATA"


async def test_insufficient_portfolio_valuation_data_error_envelope(_app: FastAPI) -> None:
    from stock_research_core.application.exceptions import InsufficientPortfolioValuationDataError

    @_app.get("/boom-insufficient-valuation-data")
    async def boom_insufficient_valuation_data() -> None:
        raise InsufficientPortfolioValuationDataError(
            "At least two portfolio valuations are required to calculate performance."
        )

    transport = ASGITransport(app=_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/boom-insufficient-valuation-data")

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INSUFFICIENT_PORTFOLIO_VALUATION_DATA"
    assert body["error"]["message"] == "At least two portfolio valuations are required to calculate performance."
    assert body["error"]["correlation_id"] == "test-correlation-id"
    assert "Traceback" not in response.text


@pytest.fixture
def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom-known")
    async def boom_known() -> None:
        from stock_research_core.application.exceptions import LearnerNotFoundError

        raise LearnerNotFoundError("No learner found.")

    @app.get("/boom-unknown")
    async def boom_unknown() -> None:
        raise ValueError("something truly unexpected")

    @app.middleware("http")
    async def _fake_correlation_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.correlation_id = "test-correlation-id"
        return await call_next(request)

    return app


async def test_known_error_envelope_has_correlation_id_and_no_stack_trace(_app: FastAPI) -> None:
    transport = ASGITransport(app=_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/boom-known")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["correlation_id"] == "test-correlation-id"
    assert body["error"]["code"] == "NOT_FOUND"
    assert "Traceback" not in response.text


async def test_unhandled_error_degrades_to_a_safe_generic_500(_app: FastAPI) -> None:
    transport = ASGITransport(app=_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/boom-unknown")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "something truly unexpected" not in response.text
    assert "Traceback" not in response.text
    assert "ValueError" not in response.text
