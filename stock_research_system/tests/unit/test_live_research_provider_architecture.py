"""Architecture/import-boundary checks for the Phase G2A1 Live Research
provider contracts and adapters. AST-based - mirrors the equivalent checks
in `test_ai_tutor_architecture.py`.

The forbidden-import detector inspects *full dotted import paths*, not
just root module names. A root-name-only check (e.g. one that reduces
`from stock_research_core.infrastructure.operations.job_registry import X`
down to just `"stock_research_core"`) can never distinguish a forbidden
internal path (background-job orchestration, the API layer, ...) from an
allowed one (e.g. the dependency-free sanitization helper) - both
collapse to the same root name. See
`TestForbiddenImportPathDetector.test_root_name_only_detection_would_have_missed_this`
for a regression proof of exactly that gap.
"""

from __future__ import annotations

import ast
import inspect

from stock_research_core.application.live_research import provider_models as provider_models_module
from stock_research_core.application.live_research import provider_ports as provider_ports_module
from stock_research_core.infrastructure.live_research import _http as http_helper_module
from stock_research_core.infrastructure.live_research import config as config_module
from stock_research_core.infrastructure.live_research import perplexity_search_adapter as perplexity_module
from stock_research_core.infrastructure.live_research import sec_edgar_adapter as sec_module

_FORBIDDEN_EXTERNAL_ROOT_MODULES = {
    "sqlalchemy",
    "asyncpg",
    "celery",
    "redis",
    "fastapi",
    "uvicorn",
    "n8n",
    "openai",
    "anthropic",
    "langgraph",
    "ollama",
}

# Full internal path prefixes that must never be imported by a G2A1
# provider-contract or adapter module: background-job orchestration, the
# FastAPI-facing API layer, and the domain.operations package (which also
# holds job/orchestration models) - except the one exact, dependency-free
# module explicitly allowlisted below.
_FORBIDDEN_INTERNAL_PATH_PREFIXES = (
    "stock_research_core.infrastructure.operations",
    "stock_research_core.application.operations",
    "stock_research_core.api",
    "stock_research_core.domain.operations",
)

# The sole exception: a pure, dependency-free helper module that happens
# to live under `domain.operations` but carries no job/orchestration
# concept - see its own docstring. Do not move or duplicate it in this
# phase; only allowlist its exact path.
_ALLOWED_INTERNAL_PATHS = frozenset({"stock_research_core.domain.operations.sanitization"})


def _imported_full_paths(source: str) -> set[str]:
    """Every module path this source imports from, as full dotted
    strings - e.g. `from a.b.c import d` contributes `"a.b.c"`, and
    `import a.b.c` contributes `"a.b.c"`."""
    tree = ast.parse(source)
    paths: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                paths.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            paths.add(node.module)
    return paths


def _root_modules(paths: set[str]) -> set[str]:
    return {path.split(".")[0] for path in paths}


def _is_forbidden_path(path: str) -> bool:
    if path in _ALLOWED_INTERNAL_PATHS:
        return False
    if path.split(".")[0] in _FORBIDDEN_EXTERNAL_ROOT_MODULES:
        return True
    return any(path == prefix or path.startswith(prefix + ".") for prefix in _FORBIDDEN_INTERNAL_PATH_PREFIXES)


def _find_forbidden_imports_in_source(source: str) -> set[str]:
    """The full-import-path forbidden-dependency detector: flags
    forbidden external root packages (celery, fastapi, ...) and forbidden
    internal path prefixes (stock_research_core.infrastructure.operations,
    stock_research_core.application.operations, stock_research_core.api,
    stock_research_core.domain.operations), while explicitly allowing the
    exact, dependency-free sanitization helper module even though its
    path happens to contain `domain.operations`."""
    return {path for path in _imported_full_paths(source) if _is_forbidden_path(path)}


def _find_forbidden_imports(module: object) -> set[str]:
    return _find_forbidden_imports_in_source(inspect.getsource(module))


class TestApplicationLayerPurity:
    def test_provider_models_have_no_httpx_or_infrastructure_import(self) -> None:
        paths = _imported_full_paths(inspect.getsource(provider_models_module))
        roots = _root_modules(paths)
        assert "httpx" not in roots
        assert not any(path == "stock_research_core.infrastructure" or path.startswith(
            "stock_research_core.infrastructure."
        ) for path in paths)

    def test_provider_ports_have_no_httpx_or_infrastructure_import(self) -> None:
        paths = _imported_full_paths(inspect.getsource(provider_ports_module))
        assert not any("httpx" in path for path in paths)
        assert not any("infrastructure" in path for path in paths)

    def test_provider_models_have_no_forbidden_imports(self) -> None:
        assert _find_forbidden_imports(provider_models_module) == set()


class TestInfrastructureAdaptersHaveNoOrchestrationImports:
    def test_perplexity_adapter_has_no_forbidden_imports(self) -> None:
        assert _find_forbidden_imports(perplexity_module) == set()

    def test_sec_adapter_has_no_forbidden_imports(self) -> None:
        assert _find_forbidden_imports(sec_module) == set()

    def test_http_helper_has_no_forbidden_imports(self) -> None:
        assert _find_forbidden_imports(http_helper_module) == set()

    def test_config_has_no_forbidden_imports(self) -> None:
        assert _find_forbidden_imports(config_module) == set()

    def test_config_has_no_httpx_import(self) -> None:
        """Constructing settings must never be able to make a network
        call - enforced structurally by never importing httpx here."""
        roots = _root_modules(_imported_full_paths(inspect.getsource(config_module)))
        assert "httpx" not in roots


class TestForbiddenImportPathDetector:
    """Proves the detector examines full dotted paths, not just root
    module names, and that the sanitization helper is allowlisted by
    exact path rather than by broadly exempting all of domain.operations.
    """

    def test_detects_forbidden_internal_job_orchestration_path(self) -> None:
        source = "from stock_research_core.infrastructure.operations.job_registry import JobHandler\n"
        assert _find_forbidden_imports_in_source(source) == {
            "stock_research_core.infrastructure.operations.job_registry"
        }

    def test_detects_forbidden_application_operations_path(self) -> None:
        source = "from stock_research_core.application.operations.job_registry import BackgroundJobService\n"
        assert _find_forbidden_imports_in_source(source) == {
            "stock_research_core.application.operations.job_registry"
        }

    def test_detects_forbidden_api_path(self) -> None:
        source = "from stock_research_core.api.exception_handlers import register_handlers\n"
        assert _find_forbidden_imports_in_source(source) == {"stock_research_core.api.exception_handlers"}

    def test_detects_forbidden_domain_operations_job_module(self) -> None:
        source = "from stock_research_core.domain.operations.models import BackgroundJob\n"
        assert _find_forbidden_imports_in_source(source) == {"stock_research_core.domain.operations.models"}

    def test_allows_exact_sanitization_module(self) -> None:
        source = "from stock_research_core.domain.operations.sanitization import contains_traceback\n"
        assert _find_forbidden_imports_in_source(source) == set()

    def test_detects_forbidden_external_root_module_via_import(self) -> None:
        assert _find_forbidden_imports_in_source("import celery\n") == {"celery"}

    def test_detects_forbidden_external_root_module_via_import_from(self) -> None:
        assert _find_forbidden_imports_in_source("from fastapi import FastAPI\n") == {"fastapi"}

    def test_root_name_only_detection_would_have_missed_this(self) -> None:
        """Regression proof: reducing every import to its root module
        name collapses both the forbidden internal path and the allowed
        sanitization path down to the same string, `"stock_research_core"`
        - a root-only check can never tell them apart. The full-path
        detector must (and does)."""
        forbidden_source = "from stock_research_core.infrastructure.operations.job_registry import JobHandler\n"
        allowed_source = "from stock_research_core.domain.operations.sanitization import contains_traceback\n"

        forbidden_roots = _root_modules(_imported_full_paths(forbidden_source))
        allowed_roots = _root_modules(_imported_full_paths(allowed_source))
        assert forbidden_roots == allowed_roots == {"stock_research_core"}  # indistinguishable by root alone

        assert _find_forbidden_imports_in_source(forbidden_source) != set()
        assert _find_forbidden_imports_in_source(allowed_source) == set()


class TestNoRealSecretsInTrackedTestData:
    def test_fake_credentials_are_obviously_fake(self) -> None:
        """The fake API key / User-Agent literals used across the G2A1
        test suite are structurally obvious placeholders, not real
        secrets: they embed a 'test-only'/'example.com' marker."""
        import tests.unit.test_live_research_provider_config as config_tests
        import tests.unit.test_perplexity_search_adapter as perplexity_tests
        import tests.unit.test_sec_edgar_adapter as sec_tests

        assert "test-only" in perplexity_tests._FAKE_API_KEY
        assert "test-only" in config_tests._FAKE_PERPLEXITY_KEY
        assert "example.com" in sec_tests._USER_AGENT
        assert "example.com" in config_tests._VALID_SEC_USER_AGENT
