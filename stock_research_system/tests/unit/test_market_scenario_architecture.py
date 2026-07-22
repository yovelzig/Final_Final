"""Architecture/import-boundary checks for the historical market
scenario engine.

AST-based (no actual import side effects are exercised beyond what's
already imported for other tests) - mirrors the equivalent checks
written for Phase 4 adaptive learning in `test_adaptive_architecture.py`.
"""

from __future__ import annotations

import ast
import inspect

from stock_research_core.application.market_scenarios import calculator as calculator_module
from stock_research_core.application.market_scenarios import grading as grading_module
from stock_research_core.application.market_scenarios import models as application_models_module
from stock_research_core.application.market_scenarios import orchestrator as orchestrator_module
from stock_research_core.application.market_scenarios import ports as ports_module
from stock_research_core.application.market_scenarios import service as service_module
from stock_research_core.domain.market_scenarios import enums as domain_enums_module
from stock_research_core.domain.market_scenarios import models as domain_models_module

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

_APPLICATION_MODULES = (
    application_models_module,
    ports_module,
    calculator_module,
    grading_module,
    service_module,
    orchestrator_module,
)


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


def test_domain_market_scenarios_package_has_no_infrastructure_imports() -> None:
    for module in (domain_enums_module, domain_models_module):
        imported = _imported_root_modules(module)
        assert imported.isdisjoint(_FORBIDDEN_INFRASTRUCTURE), (
            f"{module.__name__} imports {imported & _FORBIDDEN_INFRASTRUCTURE}"
        )


def test_domain_market_scenarios_does_not_import_market_data_or_learning_models() -> None:
    """The domain layer references the market-data and learning domains
    only by UUID (plus the shared `DomainModel`/`utc_now` base - the
    same "except pure Pydantic configuration" exception documented in
    `domain.learning.models` - and the small, reused `ConfidenceLevel`
    enum) - never by importing `Security`, `MarketBar`, `Exercise`, or
    any other concrete domain object from those packages."""
    tree = ast.parse(inspect.getsource(domain_models_module))
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "stock_research_core.domain.models":
            imported_names.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module == "stock_research_core.domain.learning.models":
            imported_names.update(alias.name for alias in node.names)
    allowed = {"DomainModel", "utc_now"}
    assert imported_names <= allowed, f"domain.market_scenarios.models imports {imported_names - allowed}"


def test_application_market_scenarios_package_has_no_infrastructure_imports() -> None:
    for module in _APPLICATION_MODULES:
        imported = _imported_root_modules(module)
        assert imported.isdisjoint(_FORBIDDEN_INFRASTRUCTURE), (
            f"{module.__name__} imports {imported & _FORBIDDEN_INFRASTRUCTURE}"
        )


def test_application_market_scenarios_ports_are_pure_protocols() -> None:
    """`ports.py` must never import a concrete repository implementation
    (only actual import statements count - the module's docstring
    legitimately mentions "infrastructure" in prose)."""
    imported_paths = _imported_full_module_paths(ports_module)
    assert not any("infrastructure" in path for path in imported_paths)


def test_calculator_and_grading_modules_declare_no_concrete_infrastructure() -> None:
    for module in (calculator_module, grading_module):
        imported_paths = _imported_full_module_paths(module)
        assert not any("infrastructure" in path for path in imported_paths)


def test_service_never_calls_datetime_now_directly() -> None:
    """Time must always come from the injected `clock`, never
    `datetime.now()` or `datetime.utcnow()`, so tests can be fully
    deterministic."""
    assert _calls_matching(service_module, "datetime.now") == []
    assert _calls_matching(service_module, "datetime.utcnow") == []


def test_service_never_calls_asyncio_to_thread() -> None:
    """`asyncio.to_thread` (pandas/NumPy offloading) belongs only in the
    infrastructure calculator - the application service just awaits the
    `ScenarioCalculatorPort` it was given."""
    assert _calls_matching(service_module, "asyncio.to_thread") == []


def test_application_market_scenarios_service_does_not_import_concrete_repositories() -> None:
    for module in (service_module, orchestrator_module):
        imported_paths = _imported_full_module_paths(module)
        assert not any("infrastructure.database.repositories" in path for path in imported_paths)
        assert not any("infrastructure.database.orm" in path for path in imported_paths)
        assert not any("infrastructure.market_scenarios" in path for path in imported_paths)


def test_orchestrator_reuses_scenario_service_instead_of_duplicating_grading() -> None:
    source = inspect.getsource(orchestrator_module)
    assert "grade_answer" not in source
    assert ".grade(" not in source
    assert "submit_decision" in source
    assert "record_completed_activity" in source


def test_repository_ports_have_no_sqlalchemy_leakage_in_signatures() -> None:
    """A Protocol method's return type must never be an ORM row - the
    return annotations should only reference domain/application models."""
    source = inspect.getsource(ports_module)
    assert "ORM" not in source


def test_grading_policy_never_reads_a_scenario_outcome_when_grading() -> None:
    source = inspect.getsource(grading_module)
    grade_method_source = source[source.index("def grade(") : source.index("def calculate_outcome_alignment(")]
    assert "outcome" not in grade_method_source.lower()


def test_learner_scenario_view_structurally_cannot_carry_future_data() -> None:
    forbidden_fields = {"outcome", "reveal_end_at", "future_focal_chart", "future_benchmark_chart", "rubrics"}
    assert forbidden_fields.isdisjoint(application_models_module.LearnerScenarioView.model_fields)
    assert "is_correct" not in application_models_module.LearnerSafeExerciseOption.model_fields


def test_importing_market_scenario_packages_does_not_touch_the_database() -> None:
    """Import-time side effects only - no engine, no session, no connection."""
    for module in (domain_enums_module, domain_models_module, *_APPLICATION_MODULES):
        source = inspect.getsource(module)
        assert "create_engine" not in source
        assert "create_database_engine" not in source
