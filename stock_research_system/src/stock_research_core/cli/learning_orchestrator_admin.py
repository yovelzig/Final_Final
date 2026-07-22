"""Administrative CLI for the Phase 12 LangGraph learning orchestrator.

One-time (idempotent) LangGraph checkpoint-table setup - never run
automatically by the API on startup:

    python -m stock_research_core.cli.learning_orchestrator_admin --setup-checkpointer

Validate the graph compiles with an in-memory checkpointer (no database
required):

    python -m stock_research_core.cli.learning_orchestrator_admin --validate-graph

Inspect a thread's FinQuest-owned audit state and its LangGraph
orchestration position:

    python -m stock_research_core.cli.learning_orchestrator_admin --thread-status <UUID>
    python -m stock_research_core.cli.learning_orchestrator_admin --run-status <UUID>

Close a thread (admin override - no learner-ownership check):

    python -m stock_research_core.cli.learning_orchestrator_admin --close-thread <UUID>

Delete a thread's LangGraph checkpoint history (requires explicit
confirmation; never touches the FinQuest audit tables - threads/runs/
events/action_proposals are untouched):

    python -m stock_research_core.cli.learning_orchestrator_admin `
      --delete-checkpoint-thread <UUID> --confirm-delete

This module is a composition root: it is one of the few places outside
the infrastructure layer allowed to import concrete adapters directly.
It always disposes every resource it opens, even on error.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from stock_research_core.application.exceptions import StockResearchError
from stock_research_core.application.learning_orchestrator.graph_builder import GRAPH_NAME, GRAPH_VERSION, build_graph
from stock_research_core.application.learning_orchestrator.nodes import GraphNodes, NodeDependencies
from stock_research_core.application.learning_orchestrator.subgraphs import Subgraphs, SubgraphDependencies
from stock_research_core.domain.models import utc_now
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import create_database_engine, create_session_factory
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from stock_research_core.infrastructure.learning_orchestrator.event_loop import (
    ensure_windows_compatible_event_loop_policy,
)
from stock_research_core.infrastructure.learning_orchestrator.graph_runtime import LangGraphOrchestratorRuntime
from stock_research_core.infrastructure.learning_orchestrator.postgres_checkpointer import (
    build_checkpointer,
    build_checkpointer_pool,
    setup_checkpointer_tables,
    to_psycopg_conninfo,
)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stock_research_core.cli.learning_orchestrator_admin",
        description="Administer the FinQuest LangGraph learning orchestrator.",
    )
    parser.add_argument("--setup-checkpointer", action="store_true")
    parser.add_argument("--validate-graph", action="store_true")
    parser.add_argument("--thread-status", default=None, metavar="UUID")
    parser.add_argument("--run-status", default=None, metavar="UUID")
    parser.add_argument("--close-thread", default=None, metavar="UUID")
    parser.add_argument("--delete-checkpoint-thread", default=None, metavar="UUID")
    parser.add_argument(
        "--confirm-delete", action="store_true",
        help="Required alongside --delete-checkpoint-thread - deletes LangGraph checkpoint history only.",
    )
    return parser


async def _setup_checkpointer(conninfo: str) -> None:
    await setup_checkpointer_tables(conninfo)
    print("LangGraph checkpoint tables are set up (idempotent - safe to re-run).")


async def _validate_graph() -> None:
    from langgraph.checkpoint.memory import InMemorySaver

    class _UnusedPort:
        def __getattr__(self, name: str):  # pragma: no cover - defensive only
            raise AssertionError(f"--validate-graph must never invoke '{name}'; it only checks graph structure.")

    node_deps = NodeDependencies(
        unit_of_work_factory=lambda: _UnusedPort(), intent_classifier=_UnusedPort(), context_loader=_UnusedPort(),
        action_executor=_UnusedPort(), guardrail=_UnusedPort(), clock=utc_now,
    )
    subgraph_deps = SubgraphDependencies(
        tutor_service=_UnusedPort(), lesson_tutor_service=_UnusedPort(), scenario_tutor_service=_UnusedPort(),
        portfolio_tutor_service=_UnusedPort(), adaptive_learning_service=_UnusedPort(), context_loader=_UnusedPort(),
    )
    compiled = build_graph(
        graph_nodes=GraphNodes(node_deps), subgraphs=Subgraphs(subgraph_deps), checkpointer=InMemorySaver()
    )
    graph_repr = compiled.get_graph()
    print(f"Graph '{GRAPH_NAME}' (version {GRAPH_VERSION}) compiled successfully.")
    print(f"  nodes: {len(graph_repr.nodes)}")
    print(f"  edges: {len(graph_repr.edges)}")
    for node_name in sorted(graph_repr.nodes):
        print(f"    - {node_name}")


async def _thread_status(uow_factory, *, thread_id: str, graph_runtime: LangGraphOrchestratorRuntime) -> None:
    async with uow_factory() as uow:
        thread = await uow.learning_orchestrator_threads.get_by_id(UUID(thread_id))
    if thread is None:
        raise StockResearchError(f"No thread found with id '{thread_id}'.")
    print(f"thread_id:            {thread.thread_id}")
    print(f"learner_id:           {thread.learner_id}")
    print(f"status:                {thread.status.value}")
    print(f"title:                 {thread.title}")
    print(f"current_context_type:  {thread.current_context_type.value}")
    print(f"created_at:            {thread.created_at.isoformat()}")
    print(f"closed_at:             {thread.closed_at.isoformat() if thread.closed_at else '-'}")

    state = await graph_runtime.get_state(thread_id=thread_id)
    if state is None:
        print("\nNo LangGraph checkpoint state exists for this thread yet.")
        return
    print("\nLangGraph orchestration position (bounded state - never raw checkpoint bytes):")
    print(f"  step_count:      {state.get('step_count')}")
    print(f"  selected_route:  {state.get('selected_route')}")
    print(f"  intent:          {(state.get('intent_classification') or {}).get('intent')}")


async def _run_status(uow_factory, *, run_id: str) -> None:
    async with uow_factory() as uow:
        run = await uow.learning_orchestrator_runs.get_by_id(UUID(run_id))
        if run is None:
            raise StockResearchError(f"No run found with id '{run_id}'.")
        events = await uow.learning_orchestrator_events.list_for_run(run.run_id)
    print(f"run_id:        {run.run_id}")
    print(f"thread_id:     {run.thread_id}")
    print(f"status:        {run.status.value}")
    print(f"intent:        {run.intent.value if run.intent else '-'}")
    print(f"route:         {run.route.value if run.route else '-'}")
    print(f"step_count:    {run.step_count}/{run.maximum_steps}")
    print(f"failure_code:  {run.failure_code or '-'}")
    print(f"\nEvents ({len(events)}):")
    for event in events:
        print(f"  #{event.sequence_number} {event.created_at.isoformat()} {event.event_type.value}: {event.learner_message}")


async def _close_thread(uow_factory, *, thread_id: str) -> None:
    async with uow_factory() as uow:
        closed = await uow.learning_orchestrator_threads.close(UUID(thread_id), closed_at=utc_now())
        await uow.commit()
    print(f"Closed thread: {closed.thread_id} status={closed.status.value}")


async def _delete_checkpoint_thread(checkpointer, *, thread_id: str, confirmed: bool) -> None:
    if not confirmed:
        raise StockResearchError(
            "--delete-checkpoint-thread requires --confirm-delete. This deletes LangGraph checkpoint "
            "history only - it never touches FinQuest's own thread/run/event/action_proposal audit rows."
        )
    await checkpointer.adelete_thread(thread_id)
    print(f"Deleted LangGraph checkpoint history for thread '{thread_id}'. FinQuest audit rows were not touched.")


async def _run(args: argparse.Namespace) -> int:
    if args.validate_graph:
        await _validate_graph()
        return 0

    ensure_windows_compatible_event_loop_policy()
    database_settings = DatabaseSettings()
    conninfo = to_psycopg_conninfo(database_settings.database_url)

    if args.setup_checkpointer:
        await _setup_checkpointer(conninfo)
        return 0

    engine = create_database_engine(database_settings)
    session_factory = create_session_factory(engine)
    uow_factory = lambda: SqlAlchemyUnitOfWork(session_factory)  # noqa: E731

    pool = build_checkpointer_pool(conninfo, min_size=1, max_size=2)
    await pool.open()
    checkpointer = build_checkpointer(pool)

    try:
        if args.thread_status:
            graph_runtime = LangGraphOrchestratorRuntime(graph=_dummy_compiled_graph(checkpointer))
            await _thread_status(uow_factory, thread_id=args.thread_status, graph_runtime=graph_runtime)
            return 0

        if args.run_status:
            await _run_status(uow_factory, run_id=args.run_status)
            return 0

        if args.close_thread:
            await _close_thread(uow_factory, thread_id=args.close_thread)
            return 0

        if args.delete_checkpoint_thread:
            await _delete_checkpoint_thread(
                checkpointer, thread_id=args.delete_checkpoint_thread, confirmed=args.confirm_delete
            )
            return 0

        print(
            "error: specify one of --setup-checkpointer, --validate-graph, --thread-status, "
            "--run-status, --close-thread, or --delete-checkpoint-thread",
            file=sys.stderr,
        )
        return 2
    except StockResearchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        await pool.close()
        await engine.dispose()


def _dummy_compiled_graph(checkpointer):
    """`--thread-status` only needs `aget_state` from the *real* compiled
    graph - build it with an intentionally inert node/subgraph dependency
    set (never invoked, since this path never calls `ainvoke`/`astream`)."""

    class _UnusedPort:
        def __getattr__(self, name: str):  # pragma: no cover - defensive only
            raise AssertionError(f"'{name}' must never be invoked from --thread-status.")

    node_deps = NodeDependencies(
        unit_of_work_factory=lambda: _UnusedPort(), intent_classifier=_UnusedPort(), context_loader=_UnusedPort(),
        action_executor=_UnusedPort(), guardrail=_UnusedPort(), clock=utc_now,
    )
    subgraph_deps = SubgraphDependencies(
        tutor_service=_UnusedPort(), lesson_tutor_service=_UnusedPort(), scenario_tutor_service=_UnusedPort(),
        portfolio_tutor_service=_UnusedPort(), adaptive_learning_service=_UnusedPort(), context_loader=_UnusedPort(),
    )
    return build_graph(
        graph_nodes=GraphNodes(node_deps), subgraphs=Subgraphs(subgraph_deps), checkpointer=checkpointer
    )


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
