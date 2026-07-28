"""Unit tests for `IntegrationClientAdminService` (Phase G2C).

Uses a simple in-memory fake `IntegrationClientRepositoryPort` backed by a
real `asyncio.Lock` to faithfully model `get_for_update`'s row-lock
semantics (including genuine interleaving under concurrent callers) - no
SQLAlchemy, no PostgreSQL.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from stock_research_core.application.exceptions import (
    IntegrationClientFinalJobTypeError,
    IntegrationClientNotFoundError,
)
from stock_research_core.application.operations.integration_client_admin_service import (
    IntegrationClientAdminService,
)
from stock_research_core.domain.operations.enums import BackgroundJobType, IntegrationClientStatus
from stock_research_core.domain.operations.models import IntegrationClient

pytestmark = pytest.mark.asyncio


def _client(**overrides: object) -> IntegrationClient:
    defaults: dict = dict(
        name="n8n canary", key_id=f"key-{uuid4().hex[:12]}", api_key_hash="a" * 64,
        status=IntegrationClientStatus.ACTIVE,
        allowed_job_types=[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION],
    )
    defaults.update(overrides)
    return IntegrationClient(**defaults)


class _SharedStore:
    def __init__(self) -> None:
        self.clients: dict[UUID, IntegrationClient] = {}
        self.lock = asyncio.Lock()
        # Every successful get_for_update() call, in order - proves each
        # grant/revoke acquires the row lock rather than reading unlocked.
        self.lock_acquisitions: list[UUID] = []


class _FakeIntegrationClientRepository:
    def __init__(self, store: _SharedStore) -> None:
        self._store = store

    async def get_for_update(self, integration_id: UUID) -> IntegrationClient | None:
        await self._store.lock.acquire()
        self._store.lock_acquisitions.append(integration_id)
        # A forced yield here creates genuine interleaving windows for the
        # concurrency test below - the lock (not scheduling luck) is what
        # must keep two overlapping transactions from corrupting state.
        await asyncio.sleep(0)
        return self._store.clients.get(integration_id)

    async def get_by_id(self, integration_id: UUID) -> IntegrationClient | None:
        return self._store.clients.get(integration_id)

    async def add_allowed_job_type(self, integration_id: UUID, job_type: BackgroundJobType) -> None:
        await asyncio.sleep(0)
        client = self._store.clients[integration_id]
        if job_type not in client.allowed_job_types:
            self._store.clients[integration_id] = client.model_copy(
                update={"allowed_job_types": [*client.allowed_job_types, job_type]}
            )

    async def remove_allowed_job_type(self, integration_id: UUID, job_type: BackgroundJobType) -> None:
        await asyncio.sleep(0)
        client = self._store.clients[integration_id]
        if job_type in client.allowed_job_types:
            self._store.clients[integration_id] = client.model_copy(
                update={"allowed_job_types": [t for t in client.allowed_job_types if t != job_type]}
            )


class _FakeUnitOfWork:
    def __init__(self, store: _SharedStore) -> None:
        self._store = store
        self._lock_held = False
        self.integration_clients = _FakeIntegrationClientRepository(store)
        real_get_for_update = self.integration_clients.get_for_update

        async def _tracked_get_for_update(integration_id: UUID) -> IntegrationClient | None:
            result = await real_get_for_update(integration_id)
            self._lock_held = True
            return result

        self.integration_clients.get_for_update = _tracked_get_for_update  # type: ignore[method-assign]

    async def __aenter__(self) -> "_FakeUnitOfWork":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._lock_held:
            self._store.lock.release()
            self._lock_held = False

    async def commit(self) -> None:
        pass


@pytest.fixture
def store() -> _SharedStore:
    return _SharedStore()


@pytest.fixture
def admin_service(store: _SharedStore) -> IntegrationClientAdminService:
    return IntegrationClientAdminService(unit_of_work_factory=lambda: _FakeUnitOfWork(store))


class TestGrantJobType:
    async def test_grant_adds_one_job_type(self, admin_service: IntegrationClientAdminService, store: _SharedStore) -> None:
        client = _client(allowed_job_types=[BackgroundJobType.RETRIEVAL_EVALUATION])
        store.clients[client.integration_id] = client

        updated = await admin_service.grant_job_type(
            integration_id=client.integration_id, job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION
        )
        assert set(updated.allowed_job_types) == {
            BackgroundJobType.RETRIEVAL_EVALUATION, BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
        }

    async def test_repeated_grant_is_idempotent(self, admin_service: IntegrationClientAdminService, store: _SharedStore) -> None:
        client = _client(allowed_job_types=[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION])
        store.clients[client.integration_id] = client

        first = await admin_service.grant_job_type(
            integration_id=client.integration_id, job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION
        )
        second = await admin_service.grant_job_type(
            integration_id=client.integration_id, job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION
        )
        assert first.allowed_job_types == second.allowed_job_types == [BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION]

    async def test_grant_preserves_existing_permissions(
        self, admin_service: IntegrationClientAdminService, store: _SharedStore
    ) -> None:
        client = _client(
            allowed_job_types=[BackgroundJobType.RETRIEVAL_EVALUATION, BackgroundJobType.TRACKED_MARKET_REFRESH]
        )
        store.clients[client.integration_id] = client

        updated = await admin_service.grant_job_type(
            integration_id=client.integration_id, job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION
        )
        assert set(updated.allowed_job_types) == {
            BackgroundJobType.RETRIEVAL_EVALUATION, BackgroundJobType.TRACKED_MARKET_REFRESH,
            BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION,
        }

    async def test_grant_does_not_rotate_or_change_the_key(
        self, admin_service: IntegrationClientAdminService, store: _SharedStore
    ) -> None:
        client = _client(key_id="stable-key-id", api_key_hash="b" * 64)
        store.clients[client.integration_id] = client

        updated = await admin_service.grant_job_type(
            integration_id=client.integration_id, job_type=BackgroundJobType.RETRIEVAL_EVALUATION
        )
        assert updated.key_id == "stable-key-id"
        assert updated.api_key_hash == "b" * 64

    async def test_grant_is_a_single_commit(self, admin_service: IntegrationClientAdminService, store: _SharedStore) -> None:
        client = _client()
        store.clients[client.integration_id] = client
        commits: list[int] = []
        original_factory = admin_service._unit_of_work_factory

        def _counting_factory():
            uow = original_factory()
            original_commit = uow.commit

            async def _commit():
                commits.append(1)
                await original_commit()

            uow.commit = _commit
            return uow

        admin_service._unit_of_work_factory = _counting_factory
        await admin_service.grant_job_type(
            integration_id=client.integration_id, job_type=BackgroundJobType.RETRIEVAL_EVALUATION
        )
        assert len(commits) == 1

    async def test_grant_raises_not_found_for_unknown_client(
        self, admin_service: IntegrationClientAdminService
    ) -> None:
        with pytest.raises(IntegrationClientNotFoundError):
            await admin_service.grant_job_type(
                integration_id=uuid4(), job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION
            )

    async def test_grant_uses_row_locking(self, admin_service: IntegrationClientAdminService, store: _SharedStore) -> None:
        client = _client()
        store.clients[client.integration_id] = client
        await admin_service.grant_job_type(
            integration_id=client.integration_id, job_type=BackgroundJobType.RETRIEVAL_EVALUATION
        )
        assert store.lock_acquisitions == [client.integration_id]


class TestRevokeJobType:
    async def test_revoke_removes_one_job_type(self, admin_service: IntegrationClientAdminService, store: _SharedStore) -> None:
        client = _client(
            allowed_job_types=[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION, BackgroundJobType.RETRIEVAL_EVALUATION]
        )
        store.clients[client.integration_id] = client

        updated = await admin_service.revoke_job_type(
            integration_id=client.integration_id, job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION
        )
        assert updated.allowed_job_types == [BackgroundJobType.RETRIEVAL_EVALUATION]

    async def test_repeated_revoke_is_idempotent(self, admin_service: IntegrationClientAdminService, store: _SharedStore) -> None:
        client = _client(
            allowed_job_types=[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION, BackgroundJobType.RETRIEVAL_EVALUATION]
        )
        store.clients[client.integration_id] = client

        first = await admin_service.revoke_job_type(
            integration_id=client.integration_id, job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION
        )
        second = await admin_service.revoke_job_type(
            integration_id=client.integration_id, job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION
        )
        assert first.allowed_job_types == second.allowed_job_types == [BackgroundJobType.RETRIEVAL_EVALUATION]

    async def test_revoke_preserves_unrelated_permissions(
        self, admin_service: IntegrationClientAdminService, store: _SharedStore
    ) -> None:
        client = _client(
            allowed_job_types=[
                BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION, BackgroundJobType.RETRIEVAL_EVALUATION,
                BackgroundJobType.TRACKED_MARKET_REFRESH,
            ]
        )
        store.clients[client.integration_id] = client

        updated = await admin_service.revoke_job_type(
            integration_id=client.integration_id, job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION
        )
        assert set(updated.allowed_job_types) == {
            BackgroundJobType.RETRIEVAL_EVALUATION, BackgroundJobType.TRACKED_MARKET_REFRESH,
        }

    async def test_active_client_cannot_lose_its_final_job_type(
        self, admin_service: IntegrationClientAdminService, store: _SharedStore
    ) -> None:
        client = _client(
            status=IntegrationClientStatus.ACTIVE, allowed_job_types=[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION]
        )
        store.clients[client.integration_id] = client

        with pytest.raises(IntegrationClientFinalJobTypeError):
            await admin_service.revoke_job_type(
                integration_id=client.integration_id, job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION
            )
        # The rejected revoke must not have mutated anything.
        assert store.clients[client.integration_id].allowed_job_types == [BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION]

    async def test_disabled_client_can_be_revoked_down_to_zero_job_types(
        self, admin_service: IntegrationClientAdminService, store: _SharedStore
    ) -> None:
        client = _client(
            status=IntegrationClientStatus.DISABLED, allowed_job_types=[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION]
        )
        store.clients[client.integration_id] = client

        updated = await admin_service.revoke_job_type(
            integration_id=client.integration_id, job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION
        )
        assert updated.allowed_job_types == []

    async def test_revoke_raises_not_found_for_unknown_client(
        self, admin_service: IntegrationClientAdminService
    ) -> None:
        with pytest.raises(IntegrationClientNotFoundError):
            await admin_service.revoke_job_type(
                integration_id=uuid4(), job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION
            )

    async def test_revoke_uses_row_locking(self, admin_service: IntegrationClientAdminService, store: _SharedStore) -> None:
        client = _client(
            allowed_job_types=[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION, BackgroundJobType.RETRIEVAL_EVALUATION]
        )
        store.clients[client.integration_id] = client
        await admin_service.revoke_job_type(
            integration_id=client.integration_id, job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION
        )
        assert store.lock_acquisitions == [client.integration_id]

    async def test_concurrent_revokes_cannot_jointly_strip_the_final_permission(
        self, admin_service: IntegrationClientAdminService, store: _SharedStore
    ) -> None:
        """Two concurrent revoke calls for DIFFERENT job types on the same
        ACTIVE, two-permission client must never both succeed - the row
        lock forces the second caller to re-read the first caller's
        already-committed (now single-permission) state and correctly
        reject, rather than racing to zero permissions."""
        client = _client(
            status=IntegrationClientStatus.ACTIVE,
            allowed_job_types=[BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION, BackgroundJobType.RETRIEVAL_EVALUATION],
        )
        store.clients[client.integration_id] = client

        results = await asyncio.gather(
            admin_service.revoke_job_type(
                integration_id=client.integration_id, job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION
            ),
            admin_service.revoke_job_type(
                integration_id=client.integration_id, job_type=BackgroundJobType.RETRIEVAL_EVALUATION
            ),
            return_exceptions=True,
        )

        successes = [r for r in results if isinstance(r, IntegrationClient)]
        errors = [r for r in results if isinstance(r, BaseException)]
        assert len(successes) == 1
        assert len(errors) == 1
        assert isinstance(errors[0], IntegrationClientFinalJobTypeError)

        final_client = store.clients[client.integration_id]
        assert len(final_client.allowed_job_types) == 1, (
            "the ACTIVE client must never end up with zero allowed job types"
        )
        # Exactly one get_for_update per attempt, and they never overlapped
        # (the lock forced them to run one at a time).
        assert len(store.lock_acquisitions) == 2


class TestCliDelegatesToApplicationService:
    """The CLI's grant/revoke commands must call
    `IntegrationClientAdminService`, never `uow.integration_clients`
    directly (spec section 6), and must never print a secret."""

    async def test_cli_grant_helper_calls_the_admin_service_and_prints_no_secret(self, capsys) -> None:
        from stock_research_core.cli.operations_admin import _grant_integration_job_type

        client = _client(key_id="printed-key-id", api_key_hash="should-never-be-printed" + "a" * 40)

        class _SpyAdminService:
            def __init__(self) -> None:
                self.calls: list[tuple] = []

            async def grant_job_type(self, *, integration_id: UUID, job_type: BackgroundJobType) -> IntegrationClient:
                self.calls.append((integration_id, job_type))
                return client

        spy = _SpyAdminService()
        await _grant_integration_job_type(
            spy, integration_id=str(client.integration_id), job_type="LIVE_RESEARCH_RUN_EXECUTION"
        )

        assert spy.calls == [(client.integration_id, BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION)]
        captured = capsys.readouterr().out
        assert "should-never-be-printed" not in captured
        assert client.api_key_hash not in captured

    async def test_cli_grant_helper_rejects_a_malformed_uuid_without_calling_the_service(self, capsys) -> None:
        """Correction V2: a malformed --grant-integration-job-type UUID
        must raise a bounded StockResearchError-derived error, never call
        the admin service, and never print the rejected raw value."""
        from stock_research_core.application.exceptions import InvalidIntegrationClientIdentifierError
        from stock_research_core.cli.operations_admin import _grant_integration_job_type

        class _SpyAdminService:
            def __init__(self) -> None:
                self.calls: list[tuple] = []

            async def grant_job_type(self, *, integration_id: UUID, job_type: BackgroundJobType) -> IntegrationClient:
                self.calls.append((integration_id, job_type))
                raise AssertionError("must never be called for a malformed integration id")

        spy = _SpyAdminService()
        malformed_value = "not-a-real-uuid-at-all"
        with pytest.raises(InvalidIntegrationClientIdentifierError) as exc_info:
            await _grant_integration_job_type(spy, integration_id=malformed_value, job_type="LIVE_RESEARCH_RUN_EXECUTION")

        assert spy.calls == []
        assert malformed_value not in str(exc_info.value)
        captured = capsys.readouterr()
        assert malformed_value not in captured.out
        assert malformed_value not in captured.err

    async def test_cli_revoke_helper_calls_the_admin_service_and_prints_no_secret(self, capsys) -> None:
        from stock_research_core.cli.operations_admin import _revoke_integration_job_type

        client = _client(
            key_id="printed-key-id", api_key_hash="should-never-be-printed" + "b" * 40,
            status=IntegrationClientStatus.DISABLED, allowed_job_types=[],
        )

        class _SpyAdminService:
            def __init__(self) -> None:
                self.calls: list[tuple] = []

            async def revoke_job_type(self, *, integration_id: UUID, job_type: BackgroundJobType) -> IntegrationClient:
                self.calls.append((integration_id, job_type))
                return client

        spy = _SpyAdminService()
        await _revoke_integration_job_type(
            spy, integration_id=str(client.integration_id), job_type="LIVE_RESEARCH_RUN_EXECUTION"
        )

        assert spy.calls == [(client.integration_id, BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION)]
        captured = capsys.readouterr().out
        assert "should-never-be-printed" not in captured
        assert client.api_key_hash not in captured

    async def test_cli_revoke_helper_rejects_a_malformed_uuid_without_calling_the_service(self, capsys) -> None:
        """Correction V2: same bounded-error contract for
        --revoke-integration-job-type as for the grant helper."""
        from stock_research_core.application.exceptions import InvalidIntegrationClientIdentifierError
        from stock_research_core.cli.operations_admin import _revoke_integration_job_type

        class _SpyAdminServiceRejectsRevoke:
            def __init__(self) -> None:
                self.calls: list[tuple] = []

            async def revoke_job_type(self, *, integration_id: UUID, job_type: BackgroundJobType) -> IntegrationClient:
                self.calls.append((integration_id, job_type))
                raise AssertionError("must never be called for a malformed integration id")

        spy = _SpyAdminServiceRejectsRevoke()
        malformed_value = "<not-a-uuid>"
        with pytest.raises(InvalidIntegrationClientIdentifierError) as exc_info:
            await _revoke_integration_job_type(spy, integration_id=malformed_value, job_type="LIVE_RESEARCH_RUN_EXECUTION")

        assert spy.calls == []
        assert malformed_value not in str(exc_info.value)
        captured = capsys.readouterr()
        assert malformed_value not in captured.out
        assert malformed_value not in captured.err
