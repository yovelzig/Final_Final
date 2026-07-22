"""Context-scoped uniqueness for `knowledge_documents` (Phase 10
stabilization): fixes a bug where two different lessons (or exercises/
scenarios/local sources) with byte-identical text could not both be
ingested, because `uq_knowledge_documents_hash_version` constrained
only `(content_hash, document_version)` - with no notion of *which*
curriculum item or source the text belongs to.

The replacement constraint additionally scopes on `source_id`,
`lesson_id`, `exercise_id`, `scenario_id`, and `portfolio_context_code`,
using PostgreSQL 15+'s `NULLS NOT DISTINCT` so that documents with no
curriculum context (local uploads, where those columns are all NULL)
are still deduplicated correctly by content+version+source alone.

No existing data is destructive: this only replaces one constraint
with a strictly less restrictive one (a superset of columns), so every
row that already satisfied the old constraint continues to satisfy the
new one.

Revision ID: 0008_kb_doc_context_uniqueness
Revises: 0007_product_api_auth
Create Date: 2026-07-19

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
# Kept <=32 chars: `alembic_version.version_num` is VARCHAR(32).
revision: str = "0008_kb_doc_context_uniqueness"
down_revision: Union[str, None] = "0007_product_api_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_knowledge_documents_hash_version", "knowledge_documents", type_="unique"
    )
    op.create_unique_constraint(
        "uq_knowledge_documents_hash_version_context",
        "knowledge_documents",
        [
            "content_hash", "document_version", "source_id", "lesson_id", "exercise_id", "scenario_id",
            "portfolio_context_code",
        ],
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_knowledge_documents_hash_version_context", "knowledge_documents", type_="unique"
    )
    op.create_unique_constraint(
        "uq_knowledge_documents_hash_version", "knowledge_documents", ["content_hash", "document_version"]
    )
