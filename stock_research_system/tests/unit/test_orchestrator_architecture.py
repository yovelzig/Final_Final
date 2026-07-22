"""Architecture/import-boundary checks for the Phase 12 learning
orchestrator - mirrors `test_ai_tutor_architecture.py`.

`nodes.py`, `subgraphs.py`, and `graph_builder.py` are deliberately
*exempt* from the "no langgraph" rule (they legitimately use
`langgraph.types.interrupt`/`Command` and `StateGraph`) - the spec's
actual boundary is narrower: the application layer must never import
`AsyncPostgresSaver`/psycopg/the checkpointer internals directly (that
stays behind `LearningGraphRuntimePort`, implemented only in
`infrastructure.learning_orchestrator.graph_runtime`).
"""

from __future__ import annotations

import ast
import inspect

from stock_research_core.application.learning_orchestrator import actions as actions_module
from stock_research_core.application.learning_orchestrator import graph_builder as graph_builder_module
from stock_research_core.application.learning_orchestrator import intent as intent_module
from stock_research_core.application.learning_orchestrator import models as app_models_module
from stock_research_core.application.learning_orchestrator import nodes as nodes_module
from stock_research_core.application.learning_orchestrator import ports as ports_module
from stock_research_core.application.learning_orchestrator import routing as routing_module
from stock_research_core.application.learning_orchestrator import service as service_module
from stock_research_core.application.learning_orchestrator import state as state_module
from stock_research_core.application.learning_orchestrator import subgraphs as subgraphs_module
from stock_research_core.domain.learning_orchestrator import enums as domain_enums_module
from stock_research_core.domain.learning_orchestrator import models as domain_models_module

_FORBIDDEN_INFRASTRUCTURE = {
    "sqlalchemy", "asyncpg", "psycopg", "pgvector", "sentence_transformers", "pandas", "numpy", "scipy",
    "yfinance", "fastapi", "n8n", "openai", "anthropic", "perplexity", "redis", "celery",
}

#: The narrower rule for modules that legitimately use LangGraph's Graph
#: API (nodes/subgraphs/graph_builder) - they must still never import
#: the checkpointer implementation directly.
_FORBIDDEN_CHECKPOINTER_PATHS = ("langgraph.checkpoint.postgres", "psycopg")


def _imported_root_modules(module: object) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    return {
        alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}


def _imported_full_module_paths(module: object) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    return {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}


def test_domain_learning_orchestrator_package_has_no_infrastructure_imports() -> None:
    for module in (domain_enums_module, domain_models_module):
        imported = _imported_root_modules(module)
        assert imported.isdisjoint(_FORBIDDEN_INFRASTRUCTURE | {"langgraph"}), (
            f"{module.__name__} imports {imported & (_FORBIDDEN_INFRASTRUCTURE | {'langgraph'})}"
        )


def test_non_graph_application_modules_never_import_langgraph_or_infrastructure() -> None:
    """`ports.py`/`state.py`/`intent.py`/`routing.py`/`actions.py`/`models.py`
    are the parts of the application layer spec section 10 says must
    never depend on LangGraph directly - only `nodes.py`/`subgraphs.py`/
    `graph_builder.py` (the actual Graph API construction) may."""
    for module in (ports_module, state_module, intent_module, routing_module, actions_module, app_models_module):
        imported = _imported_root_modules(module)
        forbidden = _FORBIDDEN_INFRASTRUCTURE | {"langgraph"}
        assert imported.isdisjoint(forbidden), f"{module.__name__} imports {imported & forbidden}"


def test_graph_construction_modules_never_import_the_checkpointer_directly() -> None:
    for module in (nodes_module, subgraphs_module, graph_builder_module):
        imported_paths = _imported_full_module_paths(module)
        for path in imported_paths:
            assert not any(path.startswith(forbidden) for forbidden in _FORBIDDEN_CHECKPOINTER_PATHS), (
                f"{module.__name__} imports checkpointer internals directly: {path}"
            )


def test_service_never_imports_langgraph_or_checkpointer_types_directly() -> None:
    """spec section 10: the application layer's only window into
    LangGraph is `LearningGraphRuntimePort` - `service.py` must depend
    on the Protocol, never on `langgraph` itself."""
    imported = _imported_root_modules(service_module)
    assert "langgraph" not in imported
    assert imported.isdisjoint(_FORBIDDEN_INFRASTRUCTURE - {"redis", "celery"})


def test_application_ports_are_pure_protocols_with_no_infrastructure_import() -> None:
    imported_paths = _imported_full_module_paths(ports_module)
    assert not any("infrastructure" in path for path in imported_paths)
    assert not any("langgraph" in path for path in imported_paths)


def test_actions_module_never_imports_database_repositories_directly() -> None:
    imported_paths = _imported_full_module_paths(actions_module)
    assert not any("infrastructure.database.repositories" in path for path in imported_paths)
    assert not any("infrastructure.database.orm" in path for path in imported_paths)


def test_no_learning_action_type_targets_a_trade_or_operational_job() -> None:
    from stock_research_core.domain.learning_orchestrator.enums import LearningActionType

    forbidden_substrings = ("BUY", "SELL", "TRADE", "REBALANCE", "INGEST", "JOB")
    for action_type in LearningActionType:
        assert not any(token in action_type.value for token in forbidden_substrings)


def test_no_learning_intent_targets_stock_selection_or_prediction() -> None:
    from stock_research_core.domain.learning_orchestrator.enums import LearningIntent

    forbidden_substrings = ("STOCK_PICK", "PREDICT", "REBALANCE", "TRADE")
    for intent in LearningIntent:
        assert not any(token in intent.value for token in forbidden_substrings)


def test_classifiers_declare_a_version_and_never_use_randomness() -> None:
    from stock_research_core.application.learning_orchestrator.intent import RuleBasedLearningIntentClassifier

    assert RuleBasedLearningIntentClassifier.classifier_version

    for module in (intent_module, routing_module):
        imported = _imported_root_modules(module)
        assert "random" not in imported


def test_services_never_call_datetime_now_directly() -> None:
    def _calls_matching(module: object, dotted_call: str) -> list[ast.Call]:
        tree = ast.parse(inspect.getsource(module))
        target_parts = dotted_call.split(".")
        matches: list[ast.Call] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            parts: list[str] = [node.func.attr]
            cursor: ast.expr = node.func.value
            while isinstance(cursor, ast.Attribute):
                parts.append(cursor.attr)
                cursor = cursor.value
            if isinstance(cursor, ast.Name):
                parts.append(cursor.id)
            parts.reverse()
            if parts == target_parts:
                matches.append(node)
        return matches

    for module in (service_module, nodes_module):
        assert _calls_matching(module, "datetime.now") == []
        assert _calls_matching(module, "datetime.utcnow") == []
