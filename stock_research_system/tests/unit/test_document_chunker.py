"""Unit tests for `HeadingAwareWordChunker`."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from stock_research_core.application.ai_tutor.chunking import CHUNKING_VERSION, HeadingAwareWordChunker
from stock_research_core.domain.ai_tutor.enums import KnowledgeApprovalStatus, KnowledgeDocumentStatus
from stock_research_core.domain.ai_tutor.models import KnowledgeDocument

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _document(text: str) -> KnowledgeDocument:
    return KnowledgeDocument(
        source_id=uuid4(), title="Doc", content_text=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        status=KnowledgeDocumentStatus.PROCESSED, approval_status=KnowledgeApprovalStatus.APPROVED,
        available_at=NOW, parser_version="v1",
    )


class TestHeadingAwareWordChunker:
    def test_never_produces_empty_chunks(self) -> None:
        chunker = HeadingAwareWordChunker()
        chunks = chunker.chunk(document=_document("# Title\n\nSome short content."))
        assert all(chunk.content.strip() for chunk in chunks)

    def test_no_chunk_exceeds_max_words(self) -> None:
        chunker = HeadingAwareWordChunker()
        long_text = "# Heading\n\n" + " ".join(f"word{i}" for i in range(2000))
        chunks = chunker.chunk(document=_document(long_text))
        assert all(chunk.word_count <= 450 for chunk in chunks)

    def test_deterministic_sequential_chunk_index(self) -> None:
        chunker = HeadingAwareWordChunker()
        text = "# A\n\n" + " ".join(["word"] * 900) + "\n\n## B\n\nshort tail."
        chunks = chunker.chunk(document=_document(text))
        assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))

    def test_preserves_heading_hierarchy(self) -> None:
        chunker = HeadingAwareWordChunker()
        text = "# Top\n\nIntro text.\n\n## Sub\n\nDetail text."
        chunks = chunker.chunk(document=_document(text))
        headings = [chunk.heading_path for chunk in chunks]
        assert ["Top"] in headings
        assert ["Top", "Sub"] in headings

    def test_deterministic_repeatable_output(self) -> None:
        chunker = HeadingAwareWordChunker()
        text = "# Title\n\nRepeatable content here for hashing checks."
        first = chunker.chunk(document=_document(text))
        second = chunker.chunk(document=_document(text))
        assert [c.content_hash for c in first] == [c.content_hash for c in second]

    def test_content_hash_is_sha256_of_content(self) -> None:
        chunker = HeadingAwareWordChunker()
        chunks = chunker.chunk(document=_document("# Title\n\nHello world."))
        for chunk in chunks:
            assert chunk.content_hash == hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()

    def test_plain_text_with_no_headings_produces_empty_heading_path(self) -> None:
        chunker = HeadingAwareWordChunker()
        chunks = chunker.chunk(document=_document("Just a plain paragraph.\n\nAnother paragraph."))
        assert all(chunk.heading_path == [] for chunk in chunks)

    def test_never_requires_model_specific_tokenizer(self) -> None:
        chunker = HeadingAwareWordChunker()
        chunks = chunker.chunk(document=_document("# T\n\nA short sentence for token estimation."))
        assert all(chunk.estimated_token_count > 0 for chunk in chunks)

    def test_chunking_version_default(self) -> None:
        assert HeadingAwareWordChunker().chunking_version == CHUNKING_VERSION == "heading-word-chunker-v1"

    def test_overlap_between_split_chunks_within_same_section(self) -> None:
        chunker = HeadingAwareWordChunker()
        text = "# A\n\n" + " ".join(f"word{i}" for i in range(900))
        chunks = chunker.chunk(document=_document(text))
        assert len(chunks) >= 2
        first_words = chunks[0].content.split()
        second_words = chunks[1].content.split()
        overlap = set(first_words[-50:]) & set(second_words[:50])
        assert overlap
