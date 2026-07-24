"""Unit tests for the production-safety gate in
`scripts/seed_finquest_knowledge_base.py`. All tests are pure/mocked - no
PostgreSQL engine is ever created, no secret-shaped value is ever printed."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from stock_research_core.infrastructure.ai_tutor.production_safety import (
    UnsafeEmbeddingProviderConfigurationError,
)
from stock_research_core.infrastructure.operations.config import FinquestEnv, OperationsSettings

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "seed_finquest_knowledge_base.py"
_SPEC = importlib.util.spec_from_file_location("seed_finquest_knowledge_base", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
seed_script = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = seed_script
_SPEC.loader.exec_module(seed_script)


def _operations_settings(*, finquest_env: FinquestEnv, allow_fake_embeddings_in_production: bool) -> OperationsSettings:
    return OperationsSettings(
        finquest_env=finquest_env, allow_fake_embeddings_in_production=allow_fake_embeddings_in_production
    )


class TestValidateSeedEmbeddingSafety:
    def test_development_with_fake_embeddings_is_allowed(self) -> None:
        settings = _operations_settings(
            finquest_env=FinquestEnv.DEVELOPMENT, allow_fake_embeddings_in_production=False
        )
        result = seed_script._validate_seed_embedding_safety(
            use_real_embeddings=False, operations_settings=settings
        )
        assert result is None

    def test_production_with_fake_embeddings_and_no_override_is_rejected(self) -> None:
        settings = _operations_settings(
            finquest_env=FinquestEnv.PRODUCTION, allow_fake_embeddings_in_production=False
        )
        with pytest.raises(UnsafeEmbeddingProviderConfigurationError, match="--real-embeddings"):
            seed_script._validate_seed_embedding_safety(use_real_embeddings=False, operations_settings=settings)

    def test_production_with_real_embeddings_passes_regardless_of_override(self) -> None:
        for override in (False, True):
            settings = _operations_settings(
                finquest_env=FinquestEnv.PRODUCTION, allow_fake_embeddings_in_production=override
            )
            result = seed_script._validate_seed_embedding_safety(
                use_real_embeddings=True, operations_settings=settings
            )
            assert result is None

    def test_production_with_explicit_override_allowed_with_prominent_warning(self) -> None:
        settings = _operations_settings(
            finquest_env=FinquestEnv.PRODUCTION, allow_fake_embeddings_in_production=True
        )
        result = seed_script._validate_seed_embedding_safety(
            use_real_embeddings=False, operations_settings=settings
        )
        assert result is not None
        assert "WARNING" in result

    def test_no_case_prints_or_returns_a_secret_shaped_value(self) -> None:
        cases = [
            (FinquestEnv.DEVELOPMENT, False, False),
            (FinquestEnv.PRODUCTION, True, False),
            (FinquestEnv.PRODUCTION, True, True),
            (FinquestEnv.PRODUCTION, False, True),
        ]
        for finquest_env, use_real_embeddings, override in cases:
            settings = _operations_settings(
                finquest_env=finquest_env, allow_fake_embeddings_in_production=override
            )
            try:
                result = seed_script._validate_seed_embedding_safety(
                    use_real_embeddings=use_real_embeddings, operations_settings=settings
                )
            except UnsafeEmbeddingProviderConfigurationError as exc:
                result = str(exc)
            if result is not None:
                assert "DATABASE_URL" not in result
                assert "password" not in result.lower()


class TestRunNeverCreatesEngineWhenGateRejects:
    async def test_run_rejects_before_engine_creation(self) -> None:
        args = argparse.Namespace(
            real_embeddings=False, include_lessons=True, include_exercise_explanations=True
        )
        production_settings = _operations_settings(
            finquest_env=FinquestEnv.PRODUCTION, allow_fake_embeddings_in_production=False
        )
        with (
            patch.object(seed_script, "OperationsSettings", return_value=production_settings),
            patch.object(seed_script, "create_database_engine") as engine_mock,
        ):
            exit_code = await seed_script._run(args)
        assert exit_code == 1
        engine_mock.assert_not_called()
