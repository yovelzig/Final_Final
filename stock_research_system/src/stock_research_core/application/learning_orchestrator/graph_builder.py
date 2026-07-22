"""Explicit `StateGraph` topology for the `finquest-learning-coach`
graph (spec section 12).

Nothing here connects to PostgreSQL, Redis, or any model provider, and
nothing here runs at import time - `build_graph()` is called once per
process by `infrastructure.learning_orchestrator.graph_runtime` with an
already-constructed checkpointer and already-constructed
`GraphNodes`/`Subgraphs` dependencies. This module owns only the graph's
shape: nodes, deterministic conditional edges, and bounded topology -
never a generic prebuilt agent loop, never an unrestricted dynamic tool
registry.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from stock_research_core.application.learning_orchestrator.nodes import GraphNodes
from stock_research_core.application.learning_orchestrator.state import LearningCoachGraphState
from stock_research_core.application.learning_orchestrator.subgraphs import Subgraphs
from stock_research_core.domain.ai_tutor.enums import TutorGuardrailAction
from stock_research_core.domain.learning_orchestrator.enums import LearningOrchestratorRoute

GRAPH_NAME = "finquest-learning-coach"
GRAPH_VERSION = "learning-coach-graph-v1"

_NODE_INITIALIZE_RUN = "initialize_run"
_NODE_LOAD_CONTEXT = "load_authorized_context"
_NODE_GUARDRAIL = "evaluate_input_guardrail"
_NODE_REFUSAL = "build_refusal_response"
_NODE_FALLBACK = "build_fallback_response"
_NODE_CLASSIFY_INTENT = "classify_intent"
_NODE_SELECT_ROUTE = "select_route"
_NODE_BUILD_ACTION_PROPOSAL = "build_action_proposal"
_NODE_APPROVAL_INTERRUPT = "approval_interrupt"
_NODE_EXECUTE_ACTION = "execute_action"
_NODE_VALIDATE_OUTPUT = "validate_final_output"
_NODE_PERSIST_RESULT = "persist_final_result"

#: Route-node names are exactly the `LearningOrchestratorRoute` values
#: for the ten branchable routes - keeping the graph's node names and
#: the domain's route vocabulary identical is deliberate: it lets
#: `_route_after_select_route` be a one-line lookup instead of a second
#: parallel mapping that could drift out of sync.
_ROUTE_NODE_NAMES = (
    LearningOrchestratorRoute.GROUNDED_EXPLANATION.value,
    LearningOrchestratorRoute.LESSON_TUTOR.value,
    LearningOrchestratorRoute.EXERCISE_TUTOR.value,
    LearningOrchestratorRoute.PROGRESS_REFLECTION.value,
    LearningOrchestratorRoute.ADAPTIVE_RECOMMENDATION.value,
    LearningOrchestratorRoute.PRACTICE_ACTION.value,
    LearningOrchestratorRoute.DIAGNOSTIC_ACTION.value,
    LearningOrchestratorRoute.SCENARIO_BEFORE_TUTOR.value,
    LearningOrchestratorRoute.SCENARIO_AFTER_TUTOR.value,
    LearningOrchestratorRoute.PORTFOLIO_TUTOR.value,
)


def _route_after_guardrail(state: LearningCoachGraphState) -> str:
    action = state.get("guardrail_result", {}).get("action")
    if action == TutorGuardrailAction.REFUSE.value:
        return _NODE_REFUSAL
    if action == TutorGuardrailAction.FALLBACK.value:
        return _NODE_FALLBACK
    return _NODE_CLASSIFY_INTENT


def _route_after_select_route(state: LearningCoachGraphState) -> str:
    route = state.get("selected_route")
    if route == LearningOrchestratorRoute.FALLBACK.value:
        return _NODE_FALLBACK
    if route in _ROUTE_NODE_NAMES:
        return route
    return _NODE_FALLBACK


def _route_after_subgraph(state: LearningCoachGraphState) -> str:
    proposed_action = state.get("proposed_action")
    if proposed_action and "proposal_id" not in proposed_action:
        return _NODE_BUILD_ACTION_PROPOSAL
    return _NODE_VALIDATE_OUTPUT


def build_graph(*, graph_nodes: GraphNodes, subgraphs: Subgraphs, checkpointer: Any) -> CompiledStateGraph:
    """Constructs and compiles the parent graph. `checkpointer` is
    already-constructed (an `AsyncPostgresSaver`/`InMemorySaver`
    instance) - this function never opens a connection itself."""
    graph = StateGraph(LearningCoachGraphState)

    graph.add_node(_NODE_INITIALIZE_RUN, graph_nodes.initialize_run)
    graph.add_node(_NODE_LOAD_CONTEXT, graph_nodes.load_authorized_context)
    graph.add_node(_NODE_GUARDRAIL, graph_nodes.evaluate_input_guardrail)
    graph.add_node(_NODE_REFUSAL, graph_nodes.build_refusal_response)
    graph.add_node(_NODE_FALLBACK, graph_nodes.build_fallback_response)
    graph.add_node(_NODE_CLASSIFY_INTENT, graph_nodes.classify_intent)
    graph.add_node(_NODE_SELECT_ROUTE, graph_nodes.select_route)
    graph.add_node(_NODE_BUILD_ACTION_PROPOSAL, graph_nodes.build_action_proposal)
    graph.add_node(_NODE_APPROVAL_INTERRUPT, graph_nodes.approval_interrupt)
    graph.add_node(_NODE_EXECUTE_ACTION, graph_nodes.execute_action)
    graph.add_node(_NODE_VALIDATE_OUTPUT, graph_nodes.validate_final_output)
    graph.add_node(_NODE_PERSIST_RESULT, graph_nodes.persist_final_result)

    graph.add_node(LearningOrchestratorRoute.GROUNDED_EXPLANATION.value, subgraphs.grounded_explanation)
    graph.add_node(LearningOrchestratorRoute.LESSON_TUTOR.value, subgraphs.lesson_tutor)
    graph.add_node(LearningOrchestratorRoute.EXERCISE_TUTOR.value, subgraphs.exercise_tutor)
    graph.add_node(LearningOrchestratorRoute.PROGRESS_REFLECTION.value, subgraphs.progress_reflection)
    graph.add_node(LearningOrchestratorRoute.ADAPTIVE_RECOMMENDATION.value, subgraphs.adaptive_recommendation)
    graph.add_node(LearningOrchestratorRoute.PRACTICE_ACTION.value, subgraphs.propose_practice_session)
    graph.add_node(LearningOrchestratorRoute.DIAGNOSTIC_ACTION.value, subgraphs.propose_diagnostic_assessment)
    graph.add_node(LearningOrchestratorRoute.SCENARIO_BEFORE_TUTOR.value, subgraphs.scenario_before_tutor)
    graph.add_node(LearningOrchestratorRoute.SCENARIO_AFTER_TUTOR.value, subgraphs.scenario_after_tutor)
    graph.add_node(LearningOrchestratorRoute.PORTFOLIO_TUTOR.value, subgraphs.portfolio_tutor)

    graph.add_edge(START, _NODE_INITIALIZE_RUN)
    graph.add_edge(_NODE_INITIALIZE_RUN, _NODE_LOAD_CONTEXT)
    graph.add_edge(_NODE_LOAD_CONTEXT, _NODE_GUARDRAIL)
    graph.add_conditional_edges(
        _NODE_GUARDRAIL, _route_after_guardrail, [_NODE_REFUSAL, _NODE_FALLBACK, _NODE_CLASSIFY_INTENT]
    )
    graph.add_edge(_NODE_CLASSIFY_INTENT, _NODE_SELECT_ROUTE)
    graph.add_conditional_edges(
        _NODE_SELECT_ROUTE, _route_after_select_route, [*_ROUTE_NODE_NAMES, _NODE_FALLBACK]
    )

    for route_node_name in _ROUTE_NODE_NAMES:
        graph.add_conditional_edges(
            route_node_name, _route_after_subgraph, [_NODE_BUILD_ACTION_PROPOSAL, _NODE_VALIDATE_OUTPUT]
        )

    graph.add_edge(_NODE_BUILD_ACTION_PROPOSAL, _NODE_APPROVAL_INTERRUPT)
    graph.add_edge(_NODE_APPROVAL_INTERRUPT, _NODE_EXECUTE_ACTION)
    graph.add_edge(_NODE_EXECUTE_ACTION, _NODE_VALIDATE_OUTPUT)

    graph.add_edge(_NODE_REFUSAL, _NODE_VALIDATE_OUTPUT)
    graph.add_edge(_NODE_FALLBACK, _NODE_VALIDATE_OUTPUT)

    graph.add_edge(_NODE_VALIDATE_OUTPUT, _NODE_PERSIST_RESULT)
    graph.add_edge(_NODE_PERSIST_RESULT, END)

    return graph.compile(checkpointer=checkpointer, name=GRAPH_NAME)
