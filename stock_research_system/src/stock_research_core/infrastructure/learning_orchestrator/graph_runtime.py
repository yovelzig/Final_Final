"""`LangGraphOrchestratorRuntime`: the only concrete implementation of
`LearningGraphRuntimePort` (spec section 10 - the application layer
never imports LangGraph types directly).

Owns exactly two things the application layer must not: the compiled
`CompiledStateGraph` and the shape of a LangGraph `astream(...,
stream_mode="updates")` chunk. Everything about *what counts as
learner-safe* lives in `application.learning_orchestrator.event_stream`,
a plain-dict function this module calls but does not duplicate.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from stock_research_core.application.learning_orchestrator.event_stream import (
    error_event,
    interrupt_to_event,
    node_update_to_events,
)
from stock_research_core.application.learning_orchestrator.state import LearningCoachGraphState

DEFAULT_RUN_TIMEOUT_SECONDS = 90
DEFAULT_MAX_STEPS = 30
#: LangGraph's `recursion_limit` counts super-steps, not our own
#: `state["step_count"]` - each of our nodes is one super-step, but the
#: conditional-edge fan-out means the practical ceiling needs headroom
#: over the node-level `maximum_steps` bound enforced inside `GraphNodes`.
_RECURSION_LIMIT_MULTIPLIER = 3


class RunTimeoutError(Exception):
    """Raised when a run (or resume) exceeds `run_timeout_seconds` - a
    safe, bounded failure the service layer maps to a FAILED run."""


class LangGraphOrchestratorRuntime:
    def __init__(
        self, *, graph: CompiledStateGraph, max_steps: int = DEFAULT_MAX_STEPS,
        run_timeout_seconds: int = DEFAULT_RUN_TIMEOUT_SECONDS,
    ) -> None:
        self._graph = graph
        self._max_steps = max_steps
        self._run_timeout_seconds = run_timeout_seconds

    def _config(self, thread_id: str) -> dict[str, Any]:
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self._max_steps * _RECURSION_LIMIT_MULTIPLIER,
        }

    @staticmethod
    def _is_waiting_for_learner(result: dict[str, Any]) -> bool:
        return bool(result.get("__interrupt__"))

    # -- non-streaming -----------------------------------------------

    async def start_run(
        self, *, thread_id: str, run_id: str, initial_state: LearningCoachGraphState
    ) -> tuple[LearningCoachGraphState, bool]:
        try:
            result = await asyncio.wait_for(
                self._graph.ainvoke(initial_state, config=self._config(thread_id)),
                timeout=self._run_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise RunTimeoutError(f"Run '{run_id}' exceeded {self._run_timeout_seconds}s.") from exc
        return result, self._is_waiting_for_learner(result)

    async def resume_run(
        self, *, thread_id: str, run_id: str, resume_value: dict[str, Any]
    ) -> tuple[LearningCoachGraphState, bool]:
        try:
            result = await asyncio.wait_for(
                self._graph.ainvoke(Command(resume=resume_value), config=self._config(thread_id)),
                timeout=self._run_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise RunTimeoutError(f"Resume of run '{run_id}' exceeded {self._run_timeout_seconds}s.") from exc
        return result, self._is_waiting_for_learner(result)

    # -- streaming -----------------------------------------------

    async def stream_run(
        self, *, thread_id: str, run_id: str, initial_state: LearningCoachGraphState
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "run_started"}
        async for event in self._stream_input(initial_state, thread_id=thread_id):
            yield event

    async def stream_resume(
        self, *, thread_id: str, run_id: str, resume_value: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        async for event in self._stream_input(Command(resume=resume_value), thread_id=thread_id):
            yield event

    async def _stream_input(self, graph_input: Any, *, thread_id: str) -> AsyncIterator[dict[str, Any]]:
        config = self._config(thread_id)
        try:
            async with asyncio.timeout(self._run_timeout_seconds):
                async for chunk in self._graph.astream(graph_input, config=config, stream_mode="updates"):
                    for event in self._chunk_to_events(chunk):
                        yield event
        except TimeoutError:
            yield error_event("The run took too long and was stopped.")

    @staticmethod
    def _chunk_to_events(chunk: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for key, value in chunk.items():
            if key == "__interrupt__":
                for single_interrupt in value:
                    events.append(interrupt_to_event(single_interrupt.value))
                continue
            events.extend(node_update_to_events(key, value or {}))
        return events

    # -- state inspection -----------------------------------------------

    async def get_state(self, *, thread_id: str) -> LearningCoachGraphState | None:
        snapshot = await self._graph.aget_state(self._config(thread_id))
        if snapshot is None or not snapshot.values:
            return None
        return snapshot.values

    async def get_state_history(self, *, thread_id: str, limit: int = 20) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        async for snapshot in self._graph.aget_state_history(self._config(thread_id)):
            history.append(
                {
                    "step_count": snapshot.values.get("step_count"), "next_nodes": list(snapshot.next),
                    "created_at": snapshot.created_at,
                }
            )
            if len(history) >= limit:
                break
        return history

    async def cancel_run(self, *, thread_id: str) -> None:
        """Cooperative only, and deliberately a no-op at the graph level.

        LangGraph has no kill-switch for an in-flight `ainvoke`/`astream`,
        and every run is already bounded by `run_timeout_seconds`. Real
        cancellation semantics live in the service layer (spec section
        18): a CANCELLED `LearningOrchestratorRun` row in PostgreSQL is
        the durable source of truth, and the service simply never calls
        `resume_run` again for a cancelled, interrupted thread - it does
        not need this method to touch the checkpoint."""
        return None
