"""Application service for administering an existing `IntegrationClient`'s
job-type permissions (Phase G2C).

Grants or revokes a single `BackgroundJobType` without rotating or
revealing the client's API key, and without touching any other allowed
job type. Both operations execute inside exactly one `UnitOfWorkPort`
transaction, row-locking the target client (`get_for_update`) for the
duration of the check-then-act sequence so two concurrent revoke
requests against the same ACTIVE client cannot jointly strip its last
remaining permission.

Repository methods (`get_for_update`/`add_allowed_job_type`/
`remove_allowed_job_type`) remain persistence-only - every business rule
(idempotency, the "an ACTIVE client keeps at least one job type" rule)
lives here, not in the repository.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from stock_research_core.application.exceptions import (
    IntegrationClientFinalJobTypeError,
    IntegrationClientNotFoundError,
)
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.domain.operations.enums import BackgroundJobType, IntegrationClientStatus
from stock_research_core.domain.operations.models import IntegrationClient


class IntegrationClientAdminService:
    """Constructed once per process from an injected Unit-of-Work
    factory, exactly like every other FinQuest application service
    (e.g. `BackgroundJobService`)."""

    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWorkPort]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def grant_job_type(self, *, integration_id: UUID, job_type: BackgroundJobType) -> IntegrationClient:
        """Idempotently adds `job_type` to the client's allow-list.

        Never rotates or reveals the API key, never modifies any other
        allowed job type. One transaction, one commit.
        """
        async with self._unit_of_work_factory() as uow:
            client = await uow.integration_clients.get_for_update(integration_id)
            if client is None:
                raise IntegrationClientNotFoundError(
                    f"No integration client found with id '{integration_id}'."
                )

            if job_type not in client.allowed_job_types:
                await uow.integration_clients.add_allowed_job_type(integration_id, job_type)

            refreshed = await uow.integration_clients.get_by_id(integration_id)
            await uow.commit()

        assert refreshed is not None, "integration client vanished within its own locked transaction"
        return refreshed

    async def revoke_job_type(self, *, integration_id: UUID, job_type: BackgroundJobType) -> IntegrationClient:
        """Idempotently removes `job_type` from the client's allow-list.

        When the client is ACTIVE and `job_type` is its last remaining
        allowed job type, the revoke is rejected with
        `IntegrationClientFinalJobTypeError` rather than leaving an
        ACTIVE client that can trigger nothing - the check and the
        removal happen inside the same row-locked transaction, so two
        concurrent revoke requests against the same client cannot both
        succeed: the second blocks on the row lock until the first
        commits, then re-reads the freshly-committed (now-single) job
        type and is correctly rejected.
        """
        async with self._unit_of_work_factory() as uow:
            client = await uow.integration_clients.get_for_update(integration_id)
            if client is None:
                raise IntegrationClientNotFoundError(
                    f"No integration client found with id '{integration_id}'."
                )

            if job_type in client.allowed_job_types:
                if client.status == IntegrationClientStatus.ACTIVE and len(client.allowed_job_types) <= 1:
                    raise IntegrationClientFinalJobTypeError(
                        f"Integration client '{integration_id}' is ACTIVE and would lose its last "
                        "remaining allowed job type - grant a replacement job type first, or disable "
                        "the client before revoking its final permission."
                    )
                await uow.integration_clients.remove_allowed_job_type(integration_id, job_type)

            refreshed = await uow.integration_clients.get_by_id(integration_id)
            await uow.commit()

        assert refreshed is not None, "integration client vanished within its own locked transaction"
        return refreshed
