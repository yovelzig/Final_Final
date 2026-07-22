"""FastAPI dependencies for n8n / integration-client API-key authentication
and replay-protected job triggering (`/api/v1/integrations/n8n`).

Never uses learner JWTs - a completely separate credential and header
set from `api.dependencies`'s `get_current_principal`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from stock_research_core.api.dependencies import get_uow_factory
from stock_research_core.application.exceptions import IntegrationAuthenticationFailedError
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.domain.models import utc_now
from stock_research_core.domain.operations.enums import IntegrationClientStatus
from stock_research_core.domain.operations.models import IntegrationClient
from stock_research_core.infrastructure.operations.integration_auth import verify_api_key

_GENERIC_AUTH_FAILURE = "Authentication failed."
_MAX_HEADER_LENGTH = 256


def hash_request_body(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


async def get_integration_principal(
    request: Request,
    uow_factory: Annotated[Callable[[], UnitOfWorkPort], Depends(get_uow_factory)],
    x_finquest_key_id: Annotated[str | None, Header()] = None,
    x_finquest_integration_key: Annotated[str | None, Header()] = None,
) -> IntegrationClient:
    """Authenticate an n8n/automation client via `X-FinQuest-Key-Id` +
    `X-FinQuest-Integration-Key`. Always raises the same generic failure -
    never reveals whether a key ID exists, is disabled, or is revoked. The
    raw key is never logged (it never leaves this function as anything but
    a local variable passed to a constant-time comparison)."""
    if (
        not x_finquest_key_id
        or not x_finquest_integration_key
        or len(x_finquest_key_id) > _MAX_HEADER_LENGTH
        or len(x_finquest_integration_key) > _MAX_HEADER_LENGTH
    ):
        raise IntegrationAuthenticationFailedError(_GENERIC_AUTH_FAILURE)

    async with uow_factory() as uow:
        client = await uow.integration_clients.get_by_key_id(x_finquest_key_id)
        if client is None or client.status != IntegrationClientStatus.ACTIVE:
            raise IntegrationAuthenticationFailedError(_GENERIC_AUTH_FAILURE)
        if not verify_api_key(x_finquest_integration_key, expected_hash=client.api_key_hash):
            raise IntegrationAuthenticationFailedError(_GENERIC_AUTH_FAILURE)

        updated = await uow.integration_clients.update_last_used(client.integration_id, last_used_at=utc_now())
        await uow.commit()
    return updated


def require_external_request_id(
    x_finquest_request_id: Annotated[str | None, Header()] = None,
) -> str:
    if not x_finquest_request_id or len(x_finquest_request_id) > _MAX_HEADER_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-FinQuest-Request-ID is required and must be a non-empty, bounded-length string.",
        )
    return x_finquest_request_id


def require_idempotency_key(idempotency_key: Annotated[str | None, Header()] = None) -> str:
    if not idempotency_key or len(idempotency_key) > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key is required and must be a non-empty string of at most 200 characters.",
        )
    return idempotency_key
