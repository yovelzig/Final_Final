"""Unit tests for `infrastructure.learning_orchestrator.runtime_factory.
build_learning_orchestrator_runtime` - only the disabled-by-default path
is unit-testable without a real PostgreSQL connection (the enabled path
opens a real checkpointer pool and is covered by integration tests)."""

from __future__ import annotations

from stock_research_core.infrastructure.learning_orchestrator.config import LangGraphSettings
from stock_research_core.infrastructure.learning_orchestrator.runtime_factory import (
    build_learning_orchestrator_runtime,
)


async def test_disabled_settings_return_no_service_and_open_nothing() -> None:
    settings = LangGraphSettings(_env_file=None, langgraph_enabled=False)
    composition = await build_learning_orchestrator_runtime(
        settings=settings, database_url="postgresql+asyncpg://unused:unused@localhost/unused",
        unit_of_work_factory=lambda: None, embedding_provider=None, tutor_model=None,  # type: ignore[arg-type]
        knowledge_sufficiency_gate=None, lock_port=None, metrics=None, tracing=None,  # type: ignore[arg-type]
    )
    assert composition.service is None
    assert composition.checkpointer_pool is None
    assert composition.intent_model_client is None


async def test_coach_worker_flag_alone_does_not_enable_the_runtime() -> None:
    """`langgraph_coach_worker_enabled=True` selects *which* worker opens
    the pool - `langgraph_enabled` is still the master switch the
    factory itself checks."""
    settings = LangGraphSettings(_env_file=None, langgraph_enabled=False, langgraph_coach_worker_enabled=True)
    composition = await build_learning_orchestrator_runtime(
        settings=settings, database_url="postgresql+asyncpg://unused:unused@localhost/unused",
        unit_of_work_factory=lambda: None, embedding_provider=None, tutor_model=None,  # type: ignore[arg-type]
        knowledge_sufficiency_gate=None, lock_port=None, metrics=None, tracing=None,  # type: ignore[arg-type]
    )
    assert composition.service is None
