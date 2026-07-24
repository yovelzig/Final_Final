"""Unit tests for `stock_research_core.cli.worker_status` - the CLI used
verbatim as every worker container's Docker `HEALTHCHECK`. All checks are
mocked: no PostgreSQL, Redis, Celery broker, network access, or embedding
model is ever touched."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, patch

import pytest

from stock_research_core.cli import worker_status


def _patch_passing_checks():
    """Patches the four non-embedding checks to all report healthy."""
    return (
        patch.object(worker_status, "_check_database", AsyncMock(return_value=(True, "connected"))),
        patch.object(worker_status, "_check_redis", AsyncMock(return_value=(True, "connected"))),
        patch.object(worker_status, "_check_celery_broker", AsyncMock(return_value=(True, "broker connection established"))),
        patch.object(worker_status, "_check_registry", AsyncMock(return_value=(True, "13 job types registered"))),
    )


class TestMainAsyncWithoutRequireEmbedding:
    async def test_does_not_require_embedding_readiness(self) -> None:
        with (
            _patch_passing_checks()[0], _patch_passing_checks()[1],
            _patch_passing_checks()[2], _patch_passing_checks()[3],
        ):
            exit_code = await worker_status.main_async(require_embedding=False)
        assert exit_code == 0

    async def test_does_not_call_embedding_status_validator(self) -> None:
        with (
            patch.object(worker_status, "_check_database", AsyncMock(return_value=(True, "connected"))),
            patch.object(worker_status, "_check_redis", AsyncMock(return_value=(True, "connected"))),
            patch.object(worker_status, "_check_celery_broker", AsyncMock(return_value=(True, "ok"))),
            patch.object(worker_status, "_check_registry", AsyncMock(return_value=(True, "ok"))),
            patch.object(worker_status, "describe_embedding_provider_status") as describe_mock,
        ):
            exit_code = await worker_status.main_async(require_embedding=False)
        assert exit_code == 0
        describe_mock.assert_not_called()

    async def test_prints_not_required_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch.object(worker_status, "_check_database", AsyncMock(return_value=(True, "connected"))),
            patch.object(worker_status, "_check_redis", AsyncMock(return_value=(True, "connected"))),
            patch.object(worker_status, "_check_celery_broker", AsyncMock(return_value=(True, "ok"))),
            patch.object(worker_status, "_check_registry", AsyncMock(return_value=(True, "ok"))),
        ):
            await worker_status.main_async(require_embedding=False)
        out = capsys.readouterr().out
        assert "[OK] Embedding provider: not required for this worker" in out


class TestMainAsyncWithRequireEmbedding:
    async def test_calls_embedding_status_validator(self) -> None:
        with (
            patch.object(worker_status, "_check_database", AsyncMock(return_value=(True, "connected"))),
            patch.object(worker_status, "_check_redis", AsyncMock(return_value=(True, "connected"))),
            patch.object(worker_status, "_check_celery_broker", AsyncMock(return_value=(True, "ok"))),
            patch.object(worker_status, "_check_registry", AsyncMock(return_value=(True, "ok"))),
            patch.object(
                worker_status, "describe_embedding_provider_status",
                return_value={
                    "provider": "sentence_transformer", "environment": "production",
                    "production_approved": True, "initializable": True, "warnings": [],
                },
            ) as describe_mock,
        ):
            exit_code = await worker_status.main_async(require_embedding=True)
        describe_mock.assert_called_once()
        assert exit_code == 0

    async def test_unavailable_required_provider_fails(self) -> None:
        with (
            patch.object(worker_status, "_check_database", AsyncMock(return_value=(True, "connected"))),
            patch.object(worker_status, "_check_redis", AsyncMock(return_value=(True, "connected"))),
            patch.object(worker_status, "_check_celery_broker", AsyncMock(return_value=(True, "ok"))),
            patch.object(worker_status, "_check_registry", AsyncMock(return_value=(True, "ok"))),
            patch.object(
                worker_status, "describe_embedding_provider_status",
                return_value={
                    "provider": "sentence_transformer", "environment": "production",
                    "production_approved": True, "initializable": False, "warnings": [],
                },
            ),
        ):
            exit_code = await worker_status.main_async(require_embedding=True)
        assert exit_code == 1

    async def test_safe_available_provider_allows_success(self) -> None:
        with (
            patch.object(worker_status, "_check_database", AsyncMock(return_value=(True, "connected"))),
            patch.object(worker_status, "_check_redis", AsyncMock(return_value=(True, "connected"))),
            patch.object(worker_status, "_check_celery_broker", AsyncMock(return_value=(True, "ok"))),
            patch.object(worker_status, "_check_registry", AsyncMock(return_value=(True, "ok"))),
            patch.object(
                worker_status, "describe_embedding_provider_status",
                return_value={
                    "provider": "sentence_transformer", "environment": "production",
                    "production_approved": True, "initializable": True, "warnings": [],
                },
            ),
        ):
            exit_code = await worker_status.main_async(require_embedding=True)
        assert exit_code == 0


class TestHelpFlag:
    def test_help_exits_without_touching_checks(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch.object(worker_status, "_check_database", AsyncMock()) as db_mock,
            patch.object(worker_status, "_check_redis", AsyncMock()) as redis_mock,
        ):
            with pytest.raises(SystemExit) as exc_info:
                worker_status._build_arg_parser().parse_args(["--help"])
            assert exc_info.value.code == 0
        db_mock.assert_not_called()
        redis_mock.assert_not_called()


class TestExistingChecksStillAffectHealth:
    async def test_database_failure_fails_overall(self) -> None:
        with (
            patch.object(worker_status, "_check_database", AsyncMock(return_value=(False, "could not connect"))),
            patch.object(worker_status, "_check_redis", AsyncMock(return_value=(True, "connected"))),
            patch.object(worker_status, "_check_celery_broker", AsyncMock(return_value=(True, "ok"))),
            patch.object(worker_status, "_check_registry", AsyncMock(return_value=(True, "ok"))),
        ):
            exit_code = await worker_status.main_async(require_embedding=False)
        assert exit_code == 1

    async def test_redis_failure_fails_overall(self) -> None:
        with (
            patch.object(worker_status, "_check_database", AsyncMock(return_value=(True, "connected"))),
            patch.object(worker_status, "_check_redis", AsyncMock(return_value=(False, "ping failed"))),
            patch.object(worker_status, "_check_celery_broker", AsyncMock(return_value=(True, "ok"))),
            patch.object(worker_status, "_check_registry", AsyncMock(return_value=(True, "ok"))),
        ):
            exit_code = await worker_status.main_async(require_embedding=False)
        assert exit_code == 1

    async def test_broker_failure_fails_overall(self) -> None:
        with (
            patch.object(worker_status, "_check_database", AsyncMock(return_value=(True, "connected"))),
            patch.object(worker_status, "_check_redis", AsyncMock(return_value=(True, "connected"))),
            patch.object(worker_status, "_check_celery_broker", AsyncMock(return_value=(False, "error: timeout"))),
            patch.object(worker_status, "_check_registry", AsyncMock(return_value=(True, "ok"))),
        ):
            exit_code = await worker_status.main_async(require_embedding=False)
        assert exit_code == 1

    async def test_registry_failure_fails_overall(self) -> None:
        with (
            patch.object(worker_status, "_check_database", AsyncMock(return_value=(True, "connected"))),
            patch.object(worker_status, "_check_redis", AsyncMock(return_value=(True, "connected"))),
            patch.object(worker_status, "_check_celery_broker", AsyncMock(return_value=(True, "ok"))),
            patch.object(worker_status, "_check_registry", AsyncMock(return_value=(False, "error: bad config"))),
        ):
            exit_code = await worker_status.main_async(require_embedding=False)
        assert exit_code == 1


class TestMainEntryPoint:
    def test_main_parses_require_embedding_flag_and_exits_with_status(self) -> None:
        with (
            patch.object(sys, "argv", ["worker_status", "--require-embedding"]),
            patch.object(worker_status, "main_async", AsyncMock(return_value=0)) as main_async_mock,
        ):
            with pytest.raises(SystemExit) as exc_info:
                worker_status.main()
            assert exc_info.value.code == 0
        main_async_mock.assert_called_once_with(require_embedding=True)
