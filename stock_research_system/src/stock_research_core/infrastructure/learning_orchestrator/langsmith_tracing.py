"""Optional LangSmith tracing for the learning-coach graph (spec section
28). Disabled by default (`LANGSMITH_TRACING=false`) - no LangSmith
account is required to run FinQuest, and a missing/invalid API key or an
unreachable LangSmith endpoint must never fail a learner request. This
module only ever *configures* LangChain/LangGraph's own built-in
tracing (the standard `LANGCHAIN_TRACING_V2` / `LANGCHAIN_API_KEY` /
`LANGCHAIN_PROJECT` environment variables that `langsmith`'s tracer
reads); it never imports a LangSmith client directly, so there is
nothing here that can raise into a request path.

`trace_content=False` (the default) hides learner input/output content
from LangSmith entirely (`LANGCHAIN_HIDE_INPUTS` / `LANGCHAIN_HIDE_OUTPUTS`)
- only run/graph structure (node names, durations, step counts) is ever
traced unless an operator explicitly opts in to content tracing for a
local debugging session.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("stock_research_core.infrastructure.learning_orchestrator.langsmith_tracing")


def configure_langsmith_tracing(
    *, enabled: bool, api_key: str, project: str, trace_content: bool = False,
) -> None:
    """Sets (or clears) the environment variables LangChain/LangGraph's
    tracing reads. Called once, explicitly, from a composition root
    (`api.app_factory` or `learning_orchestrator_admin`) - never a side
    effect of importing this module."""
    if not enabled:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        return

    if not api_key:
        logger.warning("LANGSMITH_TRACING=true but no LangSmith API key was configured; leaving tracing disabled.")
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        return

    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = api_key
    os.environ["LANGCHAIN_PROJECT"] = project or "finquest-learning-coach"
    os.environ["LANGCHAIN_HIDE_INPUTS"] = "false" if trace_content else "true"
    os.environ["LANGCHAIN_HIDE_OUTPUTS"] = "false" if trace_content else "true"
