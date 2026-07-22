"""Unit test (no database) for the `knowledge_documents` uniqueness
constraint definition itself - catches an accidental regression back to
the Phase 10 stabilization bug (content+version-only uniqueness) without
needing PostgreSQL. The real reproduction/fix is verified against actual
PostgreSQL in `tests/integration/test_knowledge_ingestion_duplicate_content.py`.
"""

from __future__ import annotations

from stock_research_core.infrastructure.database.orm.knowledge_document import KnowledgeDocumentORM


def _find_constraint(name: str):
    for constraint in KnowledgeDocumentORM.__table_args__:
        if getattr(constraint, "name", None) == name:
            return constraint
    return None


def test_old_content_and_version_only_constraint_no_longer_exists() -> None:
    assert _find_constraint("uq_knowledge_documents_hash_version") is None


def test_context_scoped_constraint_covers_every_context_dimension() -> None:
    constraint = _find_constraint("uq_knowledge_documents_hash_version_context")
    assert constraint is not None
    column_names = {column.name for column in constraint.columns}
    assert column_names == {
        "content_hash", "document_version", "source_id", "lesson_id", "exercise_id", "scenario_id",
        "portfolio_context_code",
    }


def test_context_scoped_constraint_uses_nulls_not_distinct() -> None:
    """Without this, two local documents (lesson_id/exercise_id/scenario_id
    all NULL) with identical content would NOT be deduplicated, since
    standard SQL treats NULL <> NULL - breaking the idempotency guarantee
    for content with no curriculum context."""
    constraint = _find_constraint("uq_knowledge_documents_hash_version_context")
    assert constraint.dialect_options["postgresql"]["nulls_not_distinct"] is True
