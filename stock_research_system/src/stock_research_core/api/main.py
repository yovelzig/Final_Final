"""Production ASGI entry point.

    uvicorn stock_research_core.api.main:app --host 0.0.0.0 --port 8080

Importing this module builds the `FastAPI` object via `create_app()`
but performs no destructive initialization - the database engine and
every other stateful resource are created in `create_app()`'s
`lifespan`, which only runs once uvicorn actually starts serving.
"""

from __future__ import annotations

from stock_research_core.infrastructure.learning_orchestrator.event_loop import (
    ensure_windows_compatible_event_loop_policy,
)

# Phase 12: psycopg's async mode (used by the LangGraph PostgreSQL
# checkpointer) cannot run under Windows' default ProactorEventLoop -
# this must be set *before* uvicorn creates its event loop, i.e. at
# process-entry-point import time, not inside `lifespan`. A pure no-op
# on Linux/Docker (production), where the default loop is already
# compatible.
ensure_windows_compatible_event_loop_policy()

from stock_research_core.api.app_factory import create_app  # noqa: E402 - must follow the policy fix above

app = create_app()
