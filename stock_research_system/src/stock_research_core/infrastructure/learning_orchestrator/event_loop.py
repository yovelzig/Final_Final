"""A tiny, platform-guarded compatibility shim: psycopg's async mode
(used by the LangGraph PostgreSQL checkpointer) cannot run under
Windows' default `ProactorEventLoop`. This has zero effect outside
Windows - Linux (every Docker/production deployment) already uses a
compatible loop.

Must be called *before* any event loop is created for the process
(uvicorn's own loop, or a CLI's `asyncio.run(...)`) - setting the
*policy* has no effect on a loop that already exists.
"""

from __future__ import annotations

import asyncio
import sys


def ensure_windows_compatible_event_loop_policy() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
