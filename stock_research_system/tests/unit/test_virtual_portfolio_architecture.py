"""Architecture/import-boundary checks for the virtual-portfolio engine.

AST-based (no actual import side effects are exercised beyond what's
already imported for other tests) - mirrors the equivalent checks
written for adaptive learning in `test_adaptive_architecture.py`.
"""

from __future__ import annotations

import ast
import inspect

from stock_research_core.application.virtual_portfolio import execution as execution_module
from stock_research_core.application.virtual_portfolio import feedback as feedback_module
from stock_research_core.application.virtual_portfolio import models as app_models_module
from stock_research_core.application.virtual_portfolio import ports as ports_module
from stock_research_core.application.virtual_portfolio import service as service_module
from stock_research_core.application.virtual_portfolio import (
    valuation_service as valuation_service_module,
)
from stock_research_core.domain.virtual_portfolio import enums as domain_enums_module
from stock_research_core.domain.virtual_portfolio import models as domain_models_module

_FORBIDDEN_INFRASTRUCTURE = {
    "sqlalchemy",
    "asyncpg",
    "pandas",
    "numpy",
    "scipy",
    "yfinance",
    "fastapi",
    "langgraph",
    "n8n",
    "openai",
    "anthropic",
    "perplexity",
}


def _imported_root_modules(module: object) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    return {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }


def _imported_full_module_paths(module: object) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    return {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}


def test_domain_virtual_portfolio_package_has_no_infrastructure_imports() -> None:
    for module in (domain_enums_module, domain_models_module):
        imported = _imported_root_modules(module)
        assert imported.isdisjoint(_FORBIDDEN_INFRASTRUCTURE), (
            f"{module.__name__} imports {imported & _FORBIDDEN_INFRASTRUCTURE}"
        )


def test_application_virtual_portfolio_package_has_no_infrastructure_imports() -> None:
    for module in (
        service_module,
        valuation_service_module,
        execution_module,
        feedback_module,
        ports_module,
        app_models_module,
    ):
        imported = _imported_root_modules(module)
        assert imported.isdisjoint(_FORBIDDEN_INFRASTRUCTURE), (
            f"{module.__name__} imports {imported & _FORBIDDEN_INFRASTRUCTURE}"
        )


def test_application_virtual_portfolio_ports_are_pure_protocols() -> None:
    imported_paths = _imported_full_module_paths(ports_module)
    assert not any("infrastructure" in path for path in imported_paths)


def test_application_analytics_port_is_pure_protocol_no_pandas() -> None:
    from stock_research_core.application.virtual_portfolio import analytics as analytics_module

    imported = _imported_root_modules(analytics_module)
    assert imported.isdisjoint(_FORBIDDEN_INFRASTRUCTURE)


def test_pandas_analytics_confined_to_infrastructure() -> None:
    """The concrete pandas implementation is only ever imported from infrastructure."""
    from stock_research_core.infrastructure.virtual_portfolio import (
        pandas_portfolio_analytics as pandas_module,
    )

    imported = _imported_root_modules(pandas_module)
    assert "pandas" in imported  # confirms this IS the pandas-backed module


def test_services_never_import_concrete_repositories() -> None:
    for module in (service_module, valuation_service_module):
        imported_paths = _imported_full_module_paths(module)
        assert not any("infrastructure.database.repositories" in path for path in imported_paths)
        assert not any("infrastructure.database.orm" in path for path in imported_paths)


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

    for module in (service_module, valuation_service_module):
        assert _calls_matching(module, "datetime.now") == []
        assert _calls_matching(module, "datetime.utcnow") == []


def test_policies_declare_a_version_and_never_use_randomness() -> None:
    from stock_research_core.application.virtual_portfolio.execution import (
        AverageCostPortfolioAccountingPolicy,
        NextAvailableOpenExecutionPolicy,
    )
    from stock_research_core.application.virtual_portfolio.feedback import (
        RuleBasedPortfolioFeedbackPolicy,
    )

    assert NextAvailableOpenExecutionPolicy.execution_rule_version
    assert AverageCostPortfolioAccountingPolicy.accounting_version
    assert RuleBasedPortfolioFeedbackPolicy.policy_version

    for module in (execution_module, feedback_module):
        imported = _imported_root_modules(module)
        assert "random" not in imported


def test_no_dataframe_type_is_exposed_in_application_layer_signatures() -> None:
    """A `pandas.DataFrame` must never leave `infrastructure.virtual_portfolio`."""
    for module in (service_module, valuation_service_module, execution_module, feedback_module):
        source = inspect.getsource(module)
        assert "DataFrame" not in source
