"""Architecture/import-boundary checks for the grounded AI tutor.

AST-based (no actual import side effects are exercised beyond what's
already imported for other tests) - mirrors the equivalent checks
written for virtual portfolio in `test_virtual_portfolio_architecture.py`.
"""

from __future__ import annotations

import ast
import inspect

from stock_research_core.application.ai_tutor import chunking as chunking_module
from stock_research_core.application.ai_tutor import guardrails as guardrails_module
from stock_research_core.application.ai_tutor import models as app_models_module
from stock_research_core.application.ai_tutor import ports as ports_module
from stock_research_core.application.ai_tutor import prompt_builder as prompt_builder_module
from stock_research_core.application.ai_tutor import retrieval as retrieval_module
from stock_research_core.application.ai_tutor import service as service_module
from stock_research_core.domain.ai_tutor import enums as domain_enums_module
from stock_research_core.domain.ai_tutor import models as domain_models_module

_FORBIDDEN_INFRASTRUCTURE = {
    "sqlalchemy",
    "asyncpg",
    "pgvector",
    "sentence_transformers",
    "httpx",
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


def test_domain_ai_tutor_package_has_no_infrastructure_imports() -> None:
    for module in (domain_enums_module, domain_models_module):
        imported = _imported_root_modules(module)
        assert imported.isdisjoint(_FORBIDDEN_INFRASTRUCTURE), (
            f"{module.__name__} imports {imported & _FORBIDDEN_INFRASTRUCTURE}"
        )


def test_application_ai_tutor_package_has_no_infrastructure_imports() -> None:
    for module in (
        chunking_module, guardrails_module, prompt_builder_module, retrieval_module, service_module,
        ports_module, app_models_module,
    ):
        imported = _imported_root_modules(module)
        assert imported.isdisjoint(_FORBIDDEN_INFRASTRUCTURE), (
            f"{module.__name__} imports {imported & _FORBIDDEN_INFRASTRUCTURE}"
        )


def test_application_ai_tutor_ports_are_pure_protocols() -> None:
    imported_paths = _imported_full_module_paths(ports_module)
    assert not any("infrastructure" in path for path in imported_paths)


def test_services_never_import_concrete_repositories() -> None:
    for module in (service_module, retrieval_module):
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

    for module in (service_module, retrieval_module):
        assert _calls_matching(module, "datetime.now") == []
        assert _calls_matching(module, "datetime.utcnow") == []


def test_guardrail_and_chunker_declare_a_version_and_never_use_randomness() -> None:
    from stock_research_core.application.ai_tutor.chunking import HeadingAwareWordChunker
    from stock_research_core.application.ai_tutor.guardrails import RuleBasedTutorGuardrail
    from stock_research_core.application.ai_tutor.prompt_builder import GroundedTutorPromptBuilder
    from stock_research_core.application.ai_tutor.retrieval import HYBRID_RETRIEVAL_VERSION

    assert HeadingAwareWordChunker.chunking_version
    assert RuleBasedTutorGuardrail.policy_version
    assert GroundedTutorPromptBuilder.prompt_version
    assert HYBRID_RETRIEVAL_VERSION

    for module in (chunking_module, guardrails_module, retrieval_module):
        imported = _imported_root_modules(module)
        assert "random" not in imported


def _field_names(module: object, class_name: str) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    class_def = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == class_name)
    return {
        stmt.target.id
        for stmt in class_def.body
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
    }


def test_no_raw_vector_type_leaves_domain_or_application_layer() -> None:
    """`KnowledgeChunkEmbedding` carries lineage only - no vector-valued field."""
    fields = _field_names(domain_models_module, "KnowledgeChunkEmbedding")
    assert not any("vector" in name.lower() or "embedding_value" in name.lower() for name in fields)
    assert fields == {
        "embedding_id", "chunk_id", "embedding_model", "embedding_version", "embedding_dimension",
        "created_at", "updated_at",
    }


def test_tutor_model_result_has_no_hidden_reasoning_field() -> None:
    fields = _field_names(app_models_module, "TutorModelResult")
    assert not any("reasoning" in name.lower() or "chain_of_thought" in name.lower() for name in fields)
