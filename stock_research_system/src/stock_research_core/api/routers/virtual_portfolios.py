"""`/api/v1/portfolios`: virtual-portfolio creation, trade preview/execution
(idempotency-key enforced), decision journaling, and valuation/performance.

Every non-creation endpoint is ownership-checked against the caller's
own `learner_id` before any read or mutation. Trade execution requires
an `Idempotency-Key` request header - FastAPI itself returns 422 if a
client omits it, satisfying the "requires Idempotency-Key" contract
without any bespoke validation code here. Grading/accounting/valuation
logic is never duplicated here: it always flows through
`VirtualPortfolioService`/`PortfolioValuationService`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from stock_research_core.api.dependencies import (
    ensure_owned_by_learner,
    get_portfolio_service,
    get_portfolio_valuation_service,
    get_uow_factory,
    require_learner,
    require_learner_identity,
)
from stock_research_core.api.schemas.market_scenarios import SecurityResponse
from stock_research_core.api.schemas.virtual_portfolio import (
    CreatePortfolioRequest,
    ExecuteTradeRequest,
    JournalEntryResponse,
    LatestValuationResponse,
    PerformanceSummaryResponse,
    PortfolioHoldingResponse,
    PortfolioOverviewResponse,
    PortfolioTransactionResponse,
    PortfolioValuationResultResponse,
    PositionValuationResponse,
    PreviewTradeRequest,
    RecordJournalEntryRequest,
    RiskAssessmentResponse,
    TradeExecutionResponse,
    TradePreviewResponse,
    ValuationRunResponse,
    ValuationSnapshotResponse,
    ValueAsOfRequest,
    VirtualPortfolioResponse,
)
from stock_research_core.application.exceptions import SecurityNotFoundError, VirtualPortfolioNotFoundError
from stock_research_core.application.identity.models import AuthenticatedPrincipal
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.application.virtual_portfolio.service import VirtualPortfolioService
from stock_research_core.application.virtual_portfolio.valuation_service import PortfolioValuationService
from stock_research_core.domain.virtual_portfolio.models import PortfolioDecisionJournalEntry, VirtualPortfolio

router = APIRouter()

_DEFAULT_JOURNAL_LIMIT = 50


async def _get_owned_portfolio(
    uow: UnitOfWorkPort, portfolio_id: UUID, principal: AuthenticatedPrincipal
) -> VirtualPortfolio:
    portfolio = await uow.virtual_portfolios.get(portfolio_id)
    if portfolio is None:
        raise VirtualPortfolioNotFoundError(f"No virtual portfolio found with id '{portfolio_id}'.")
    ensure_owned_by_learner(
        portfolio.learner_id, principal, not_found_error=VirtualPortfolioNotFoundError,
        message=f"No virtual portfolio found with id '{portfolio_id}'.",
    )
    return portfolio


@router.get(
    "/securities/{security_id}", response_model=SecurityResponse,
    dependencies=[Depends(require_learner)],
    summary="Resolve a security id (as referenced by holdings/transactions/positions) to its ticker",
)
async def get_security(
    security_id: UUID, uow_factory: Annotated[object, Depends(get_uow_factory)]
) -> SecurityResponse:
    async with uow_factory() as uow:
        security = await uow.securities.get_by_id(security_id)
        if security is None:
            raise SecurityNotFoundError(f"No stored security found with id '{security_id}'.")
    return SecurityResponse.from_domain(security)


@router.post("", response_model=VirtualPortfolioResponse, status_code=201)
async def create_portfolio(
    payload: CreatePortfolioRequest,
    learner_id: Annotated[UUID, Depends(require_learner_identity)],
    portfolio_service: Annotated[VirtualPortfolioService, Depends(get_portfolio_service)],
) -> VirtualPortfolioResponse:
    portfolio = await portfolio_service.create_portfolio(
        learner_id=learner_id, name=payload.name, initial_cash=payload.initial_cash,
        simulation_start_at=payload.simulation_start_at, benchmark_ticker=payload.benchmark_ticker,
        allow_fractional_shares=payload.allow_fractional_shares,
        require_decision_journal=payload.require_decision_journal,
        fixed_transaction_fee=payload.fixed_transaction_fee, transaction_fee_bps=payload.transaction_fee_bps,
    )
    return VirtualPortfolioResponse.from_domain(portfolio)


@router.get("", response_model=list[VirtualPortfolioResponse])
async def list_portfolios(
    learner_id: Annotated[UUID, Depends(require_learner_identity)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
) -> list[VirtualPortfolioResponse]:
    async with uow_factory() as uow:
        portfolios = await uow.virtual_portfolios.list_for_learner(learner_id)
    return [VirtualPortfolioResponse.from_domain(p) for p in portfolios]


@router.get("/{portfolio_id}", response_model=PortfolioOverviewResponse)
async def get_portfolio(
    portfolio_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    portfolio_service: Annotated[VirtualPortfolioService, Depends(get_portfolio_service)],
) -> PortfolioOverviewResponse:
    async with uow_factory() as uow:
        await _get_owned_portfolio(uow, portfolio_id, principal)
    overview = await portfolio_service.get_overview(portfolio_id)
    return PortfolioOverviewResponse(
        portfolio=VirtualPortfolioResponse.from_domain(overview.portfolio),
        holdings=[PortfolioHoldingResponse.from_domain(h) for h in overview.holdings],
        latest_valuation=(
            ValuationSnapshotResponse.from_domain(overview.latest_valuation)
            if overview.latest_valuation else None
        ),
        position_valuations=[PositionValuationResponse.from_domain(p) for p in overview.position_valuations],
        latest_risk_assessment=(
            RiskAssessmentResponse.from_domain(overview.latest_risk_assessment)
            if overview.latest_risk_assessment else None
        ),
        recent_transactions=[PortfolioTransactionResponse.from_domain(t) for t in overview.recent_transactions],
        recent_journal_entries=[
            JournalEntryResponse.from_domain(j) for j in overview.recent_journal_entries
        ],
    )


@router.post("/{portfolio_id}/trades/preview", response_model=TradePreviewResponse)
async def preview_trade(
    portfolio_id: UUID,
    payload: PreviewTradeRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    portfolio_service: Annotated[VirtualPortfolioService, Depends(get_portfolio_service)],
) -> TradePreviewResponse:
    async with uow_factory() as uow:
        await _get_owned_portfolio(uow, portfolio_id, principal)
    preview = await portfolio_service.preview_trade(
        portfolio_id=portfolio_id, ticker=payload.ticker, transaction_type=payload.transaction_type,
        quantity=payload.quantity, requested_at=payload.requested_at,
    )
    return TradePreviewResponse(
        ticker=preview.security.ticker, transaction_type=preview.transaction_type,
        requested_quantity=preview.requested_quantity, expected_execution_at=preview.expected_execution_at,
        expected_execution_price=preview.expected_execution_price, gross_amount=preview.gross_amount,
        estimated_fee=preview.estimated_fee, estimated_cash_effect=preview.estimated_cash_effect,
        cash_before=preview.cash_before, cash_after=preview.cash_after,
        quantity_before=preview.quantity_before, quantity_after=preview.quantity_after,
        warnings=list(preview.warnings),
    )


@router.post("/{portfolio_id}/trades", response_model=TradeExecutionResponse, status_code=201)
async def execute_trade(
    portfolio_id: UUID,
    payload: ExecuteTradeRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    portfolio_service: Annotated[VirtualPortfolioService, Depends(get_portfolio_service)],
) -> TradeExecutionResponse:
    async with uow_factory() as uow:
        await _get_owned_portfolio(uow, portfolio_id, principal)

    journal_entry = None
    if payload.journal_entry is not None:
        journal_entry = PortfolioDecisionJournalEntry(
            portfolio_id=portfolio_id, learner_id=principal.learner_id, security_id=None,
            action=payload.journal_entry.action, decision_at=payload.journal_entry.decision_at,
            rationale=payload.journal_entry.rationale,
            expected_horizon_days=payload.journal_entry.expected_horizon_days,
            confidence=payload.journal_entry.confidence, risk_tags=payload.journal_entry.risk_tags,
            information_considered=payload.journal_entry.information_considered,
            assumptions=payload.journal_entry.assumptions,
        )

    result = await portfolio_service.execute_trade(
        portfolio_id=portfolio_id, ticker=payload.ticker, transaction_type=payload.transaction_type,
        quantity=payload.quantity, requested_at=payload.requested_at, idempotency_key=idempotency_key,
        journal_entry=journal_entry,
    )
    return TradeExecutionResponse(
        transaction=PortfolioTransactionResponse.from_domain(result.transaction),
        portfolio=VirtualPortfolioResponse.from_domain(result.portfolio),
        holding=PortfolioHoldingResponse.from_domain(result.holding),
        journal_entry=(
            JournalEntryResponse.from_domain(result.journal_entry) if result.journal_entry else None
        ),
    )


@router.get("/{portfolio_id}/transactions", response_model=list[PortfolioTransactionResponse])
async def list_transactions(
    portfolio_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
) -> list[PortfolioTransactionResponse]:
    async with uow_factory() as uow:
        await _get_owned_portfolio(uow, portfolio_id, principal)
        transactions = await uow.portfolio_transactions.list_for_portfolio(portfolio_id)
    return [PortfolioTransactionResponse.from_domain(t) for t in transactions]


@router.get("/{portfolio_id}/holdings", response_model=list[PortfolioHoldingResponse])
async def list_holdings(
    portfolio_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
) -> list[PortfolioHoldingResponse]:
    async with uow_factory() as uow:
        await _get_owned_portfolio(uow, portfolio_id, principal)
        holdings = await uow.portfolio_holdings.list_for_portfolio(portfolio_id)
    return [PortfolioHoldingResponse.from_domain(h) for h in holdings]


@router.post("/{portfolio_id}/journal", response_model=JournalEntryResponse, status_code=201)
async def record_journal_entry(
    portfolio_id: UUID,
    payload: RecordJournalEntryRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    portfolio_service: Annotated[VirtualPortfolioService, Depends(get_portfolio_service)],
) -> JournalEntryResponse:
    async with uow_factory() as uow:
        await _get_owned_portfolio(uow, portfolio_id, principal)
        security_id = None
        if payload.ticker is not None:
            security = await uow.securities.get_by_ticker(payload.ticker)
            if security is None:
                raise SecurityNotFoundError(f"No stored security found for ticker '{payload.ticker}'.")
            security_id = security.security_id

    entry = await portfolio_service.record_non_trade_decision(
        portfolio_id=portfolio_id, security_id=security_id, action=payload.action,
        decision_at=payload.decision_at, rationale=payload.rationale,
        expected_horizon_days=payload.expected_horizon_days, confidence=payload.confidence,
        risk_tags=payload.risk_tags, information_considered=payload.information_considered,
        assumptions=payload.assumptions,
    )
    return JournalEntryResponse.from_domain(entry)


@router.get("/{portfolio_id}/journal", response_model=list[JournalEntryResponse])
async def list_journal_entries(
    portfolio_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    limit: int = _DEFAULT_JOURNAL_LIMIT,
) -> list[JournalEntryResponse]:
    async with uow_factory() as uow:
        await _get_owned_portfolio(uow, portfolio_id, principal)
        entries = await uow.portfolio_journal.list_for_portfolio(portfolio_id, limit=limit)
    return [JournalEntryResponse.from_domain(e) for e in entries]


@router.post("/{portfolio_id}/valuations", response_model=PortfolioValuationResultResponse, status_code=201)
async def value_portfolio(
    portfolio_id: UUID,
    payload: ValueAsOfRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    valuation_service: Annotated[PortfolioValuationService, Depends(get_portfolio_valuation_service)],
) -> PortfolioValuationResultResponse:
    async with uow_factory() as uow:
        await _get_owned_portfolio(uow, portfolio_id, principal)
    result = await valuation_service.value_portfolio(portfolio_id=portfolio_id, as_of=payload.as_of)
    return PortfolioValuationResultResponse(
        run=ValuationRunResponse.from_domain(result.run),
        snapshot=ValuationSnapshotResponse.from_domain(result.snapshot),
        positions=[PositionValuationResponse.from_domain(p) for p in result.positions],
        risk_assessment=RiskAssessmentResponse.from_domain(result.risk_assessment),
    )


@router.get("/{portfolio_id}/valuations/latest", response_model=LatestValuationResponse)
async def get_latest_valuation(
    portfolio_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
) -> LatestValuationResponse:
    async with uow_factory() as uow:
        await _get_owned_portfolio(uow, portfolio_id, principal)
        snapshot = await uow.portfolio_valuations.get_latest(portfolio_id)
        positions = await uow.portfolio_valuations.list_positions(snapshot.snapshot_id) if snapshot else []
    return LatestValuationResponse(
        snapshot=ValuationSnapshotResponse.from_domain(snapshot) if snapshot else None,
        positions=[PositionValuationResponse.from_domain(p) for p in positions],
    )


@router.get("/{portfolio_id}/performance", response_model=PerformanceSummaryResponse)
async def get_performance(
    portfolio_id: UUID,
    start_at: datetime,
    end_at: datetime,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    valuation_service: Annotated[PortfolioValuationService, Depends(get_portfolio_valuation_service)],
) -> PerformanceSummaryResponse:
    async with uow_factory() as uow:
        await _get_owned_portfolio(uow, portfolio_id, principal)
    summary = await valuation_service.calculate_performance(
        portfolio_id=portfolio_id, start_at=start_at, end_at=end_at
    )
    return PerformanceSummaryResponse.from_domain(summary)
