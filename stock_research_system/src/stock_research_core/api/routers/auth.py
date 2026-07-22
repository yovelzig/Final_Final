"""`/api/v1/auth/*`: registration, login, token refresh, logout, and the
current-account profile. Every route here is a thin translation layer
over `IdentityService` - no authentication/authorization logic is
reimplemented.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from stock_research_core.api.dependencies import (
    get_client_ip_hash,
    get_correlation_id,
    get_current_principal,
    get_identity_service,
    get_uow_factory,
    get_user_agent_hash,
    rate_limit,
)
from stock_research_core.api.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutAllResponse,
    LogoutRequest,
    MeResponse,
    PublicAccount,
    PublicLearner,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenPairResponse,
)
from stock_research_core.application.identity.models import AuthenticatedPrincipal, IssuedTokenPair
from stock_research_core.application.identity.service import IdentityService

router = APIRouter()


def _token_pair_response(tokens: IssuedTokenPair) -> TokenPairResponse:
    return TokenPairResponse(
        access_token=tokens.access_token, access_token_expires_at=tokens.access_token_expires_at,
        refresh_token=tokens.refresh_token, refresh_token_expires_at=tokens.refresh_token_expires_at,
        token_type=tokens.token_type,
    )


@router.post(
    "/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED,
    summary="Register a new learner account",
    description="Creates a learner profile and a linked local account in one atomic operation, "
    "and returns an initial access/refresh token pair.",
    dependencies=[Depends(rate_limit(action="register", limit=10, window_seconds=60))],
)
async def register(
    payload: RegisterRequest,
    identity_service: Annotated[IdentityService, Depends(get_identity_service)],
    correlation_id: Annotated[str, Depends(get_correlation_id)],
    client_ip_hash: Annotated[str | None, Depends(get_client_ip_hash)],
    user_agent_hash: Annotated[str | None, Depends(get_user_agent_hash)],
) -> RegisterResponse:
    result = await identity_service.register_learner(
        email=payload.email, password=payload.password, display_name=payload.display_name,
        preferred_language=payload.preferred_language, daily_goal_minutes=payload.daily_goal_minutes,
        correlation_id=correlation_id, client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash,
    )
    return RegisterResponse(
        account=PublicAccount.from_domain(result.account), learner=PublicLearner.from_domain(result.learner),
        tokens=_token_pair_response(result.tokens),
    )


@router.post(
    "/login", response_model=LoginResponse,
    summary="Log in with email and password",
    description="Uses a generic error for both an unknown email and an incorrect password, so a "
    "caller can never learn whether an email is registered.",
    dependencies=[Depends(rate_limit(action="login", limit=10, window_seconds=60))],
)
async def login(
    payload: LoginRequest,
    identity_service: Annotated[IdentityService, Depends(get_identity_service)],
    correlation_id: Annotated[str, Depends(get_correlation_id)],
    client_ip_hash: Annotated[str | None, Depends(get_client_ip_hash)],
    user_agent_hash: Annotated[str | None, Depends(get_user_agent_hash)],
) -> LoginResponse:
    result = await identity_service.login(
        email=payload.email, password=payload.password, correlation_id=correlation_id,
        client_ip_hash=client_ip_hash, user_agent_hash=user_agent_hash,
    )
    return LoginResponse(account=PublicAccount.from_domain(result.account), tokens=_token_pair_response(result.tokens))


@router.post(
    "/refresh", response_model=TokenPairResponse,
    summary="Rotate a refresh token for a new access/refresh token pair",
    description="The supplied refresh token is immediately invalidated; reusing it afterward "
    "revokes every token issued from the same session family.",
    dependencies=[Depends(rate_limit(action="refresh", limit=20, window_seconds=60))],
)
async def refresh(
    payload: RefreshRequest,
    identity_service: Annotated[IdentityService, Depends(get_identity_service)],
    correlation_id: Annotated[str, Depends(get_correlation_id)],
    client_ip_hash: Annotated[str | None, Depends(get_client_ip_hash)],
    user_agent_hash: Annotated[str | None, Depends(get_user_agent_hash)],
) -> TokenPairResponse:
    tokens = await identity_service.refresh(
        refresh_token=payload.refresh_token, correlation_id=correlation_id, client_ip_hash=client_ip_hash,
        user_agent_hash=user_agent_hash,
    )
    return _token_pair_response(tokens)


@router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke the supplied refresh token",
    description="Idempotent: revoking an already-inactive or unknown token is not an error.",
)
async def logout(
    payload: LogoutRequest,
    identity_service: Annotated[IdentityService, Depends(get_identity_service)],
    correlation_id: Annotated[str, Depends(get_correlation_id)],
) -> None:
    await identity_service.logout(refresh_token=payload.refresh_token, correlation_id=correlation_id)


@router.post(
    "/logout-all", response_model=LogoutAllResponse,
    summary="Revoke every active session for the current account",
)
async def logout_all(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    identity_service: Annotated[IdentityService, Depends(get_identity_service)],
    correlation_id: Annotated[str, Depends(get_correlation_id)],
) -> LogoutAllResponse:
    revoked_count = await identity_service.logout_all(account_id=principal.account_id, correlation_id=correlation_id)
    return LogoutAllResponse(revoked_session_count=revoked_count)


@router.get(
    "/me", response_model=MeResponse,
    summary="Get the current account and linked learner profile",
)
async def me(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
) -> MeResponse:
    async with uow_factory() as uow:
        account = await uow.user_accounts.get_by_id(principal.account_id)
        learner = await uow.learners.get(principal.learner_id) if principal.learner_id else None
    assert account is not None
    return MeResponse(
        account=PublicAccount.from_domain(account),
        learner=PublicLearner.from_domain(learner) if learner is not None else None,
    )
