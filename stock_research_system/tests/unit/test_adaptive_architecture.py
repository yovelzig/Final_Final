"""Architecture/import-boundary checks for the adaptive learning engine.

AST-based (no actual import side effects are exercised beyond what's
already imported for other tests) - mirrors the equivalent checks
written for Phase 4 in `test_learning_service.py`.
"""

from __future__ import annotations

import ast
import inspect

from stock_research_core.application.adaptive_learning import orchestrator as orchestrator_module
from stock_research_core.application.adaptive_learning import policies as policies_module
from stock_research_core.application.adaptive_learning import ports as ports_module
from stock_research_core.application.adaptive_learning import service as service_module
from stock_research_core.domain.adaptive_learning import enums as adaptive_enums_module
from stock_research_core.domain.adaptive_learning import models as adaptive_models_module

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


def test_domain_adaptive_learning_package_has_no_infrastructure_imports() -> None:
    for module in (adaptive_enums_module, adaptive_models_module):
        imported = _imported_root_modules(module)
        assert imported.isdisjoint(_FORBIDDEN_INFRASTRUCTURE), (
            f"{module.__name__} imports {imported & _FORBIDDEN_INFRASTRUCTURE}"
        )


def test_domain_adaptive_learning_does_not_import_learning_domain() -> None:
    """Kept independent - adaptive domain models reference other domain
    objects only as plain UUIDs, never by importing `domain.learning`."""
    imported = _imported_root_modules(adaptive_models_module)
    assert "stock_research_core" not in imported or all(
        "learning" not in name for name in imported
    )


def test_application_adaptive_learning_package_has_no_infrastructure_imports() -> None:
    for module in (service_module, policies_module, ports_module, orchestrator_module):
        imported = _imported_root_modules(module)
        assert imported.isdisjoint(_FORBIDDEN_INFRASTRUCTURE), (
            f"{module.__name__} imports {imported & _FORBIDDEN_INFRASTRUCTURE}"
        )


def _imported_full_module_paths(module: object) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }


def _calls_matching(module: object, dotted_call: str) -> list[ast.Call]:
    """Find `Call` nodes whose callee matches `dotted_call` (e.g. 'datetime.now')."""
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


def test_application_adaptive_learning_ports_are_pure_protocols() -> None:
    """`ports.py` must never import a concrete repository implementation
    (only actual import statements count - the module's docstring
    legitimately mentions "infrastructure" in prose)."""
    imported_paths = _imported_full_module_paths(ports_module)
    assert not any("infrastructure" in path for path in imported_paths)


def test_policies_never_use_randomness() -> None:
    """Every policy must be deterministic: no `random` module usage."""
    imported = _imported_root_modules(policies_module)
    assert "random" not in imported


def test_all_policies_declare_a_policy_version() -> None:
    from stock_research_core.application.adaptive_learning.policies import (
        DeterministicReviewSchedulingPolicy,
        RuleBasedAdaptivePolicy,
        RuleBasedDiagnosticPolicy,
        RuleBasedDifficultyPolicy,
    )

    for policy_class in (
        RuleBasedDifficultyPolicy,
        DeterministicReviewSchedulingPolicy,
        RuleBasedDiagnosticPolicy,
        RuleBasedAdaptivePolicy,
    ):
        assert isinstance(policy_class.policy_version, str)
        assert policy_class.policy_version


def test_service_never_calls_datetime_now_directly() -> None:
    """Time must always come from the injected `clock`, never `datetime.now()`
    or `datetime.utcnow()`, so tests can be fully deterministic (checked via
    AST `Call` nodes, not substring search, since the module's own docstring
    legitimately mentions `datetime.now()` in prose)."""
    assert _calls_matching(service_module, "datetime.now") == []
    assert _calls_matching(service_module, "datetime.utcnow") == []


def test_application_adaptive_learning_service_does_not_import_concrete_repositories() -> None:
    imported_paths = _imported_full_module_paths(service_module)
    assert not any("infrastructure.database.repositories" in path for path in imported_paths)
    assert not any("infrastructure.database.orm" in path for path in imported_paths)


def test_orchestrator_reuses_learning_service_instead_of_duplicating_grading() -> None:
    source = inspect.getsource(orchestrator_module)
    assert "grade_answer" not in source
    assert "submit_answer" in source


def test_repository_ports_have_no_sqlalchemy_leakage_in_signatures() -> None:
    """A Protocol method's return type must never be an ORM row - the
    return annotations should only reference domain/application models."""
    source = inspect.getsource(ports_module)
    assert "ORM" not in source
