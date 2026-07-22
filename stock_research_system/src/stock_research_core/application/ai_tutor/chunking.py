"""Deterministic, heading-aware word chunker for the FinQuest knowledge base.

No SQLAlchemy, pgvector, sentence-transformers, or LLM-SDK dependency
here - this module only ever splits already-extracted plain text into
`KnowledgeChunk` domain objects. PDF/DOCX text extraction happens
upstream in `infrastructure.ai_tutor.local_document_parsers`; this
chunker treats every document's `content_text` as plain Markdown-ish
text (headings marked with leading `#`), which also correctly handles
`.txt` content that has no headings at all (blank-line-separated blocks
just become paragraphs under an empty heading path).

Token counts are estimated, not computed with a model-specific
tokenizer (per spec ss11): `estimated_token_count = round(word_count *
1.3)`, a widely used rule of thumb for English text tokenized by
GPT-style BPE tokenizers (~0.75 words per token). This is a documented
approximation, not an exact count.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from stock_research_core.domain.ai_tutor.models import KnowledgeChunk, KnowledgeDocument

CHUNKING_VERSION = "heading-word-chunker-v1"

_TARGET_WORDS = 350
_MAX_WORDS = 450
_OVERLAP_WORDS = 50

_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(\S.*?)\s*$")
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
_TOKENS_PER_WORD = 1.3


@dataclass
class _Section:
    heading_path: list[str]
    paragraphs: list[str] = field(default_factory=list)


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _split_into_sections(text: str) -> list[_Section]:
    """Split raw text into heading-scoped sections of blank-line-delimited paragraphs."""
    lines = _normalize_newlines(text).split("\n")
    heading_stack: list[tuple[int, str]] = []
    sections: list[_Section] = []
    current_paragraph_lines: list[str] = []
    current_paragraphs: list[str] = []

    def flush_paragraph() -> None:
        nonlocal current_paragraph_lines
        if current_paragraph_lines:
            paragraph = " ".join(line.strip() for line in current_paragraph_lines).strip()
            if paragraph:
                current_paragraphs.append(paragraph)
            current_paragraph_lines = []

    def flush_section() -> None:
        nonlocal current_paragraphs
        flush_paragraph()
        if current_paragraphs:
            sections.append(
                _Section(heading_path=[heading for _, heading in heading_stack], paragraphs=list(current_paragraphs))
            )
        current_paragraphs = []

    for line in lines:
        heading_match = _HEADING_PATTERN.match(line)
        if heading_match:
            flush_section()
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            heading_stack = [entry for entry in heading_stack if entry[0] < level]
            heading_stack.append((level, heading_text))
            continue
        if not line.strip():
            flush_paragraph()
            continue
        current_paragraph_lines.append(line)
    flush_section()
    return sections


def _split_oversized_paragraph(paragraph: str) -> list[list[str]]:
    """Split one paragraph exceeding `_MAX_WORDS` into sentence-grouped word lists, each <= `_TARGET_WORDS`."""
    sentences = _SENTENCE_SPLIT_PATTERN.split(paragraph)
    groups: list[list[str]] = []
    current: list[str] = []
    for sentence in sentences:
        words = sentence.split()
        if not words:
            continue
        if current and len(current) + len(words) > _TARGET_WORDS:
            groups.append(current)
            current = []
        if len(words) > _TARGET_WORDS:
            for start in range(0, len(words), _TARGET_WORDS):
                groups.append(words[start : start + _TARGET_WORDS])
            current = []
            continue
        current.extend(words)
    if current:
        groups.append(current)
    return groups


def _section_pieces(section: _Section) -> list[list[str]]:
    """Flatten a section's paragraphs into word-list pieces, each never exceeding `_MAX_WORDS`."""
    pieces: list[list[str]] = []
    for paragraph in section.paragraphs:
        words = paragraph.split()
        if len(words) > _MAX_WORDS:
            pieces.extend(_split_oversized_paragraph(paragraph))
        else:
            pieces.append(words)
    return pieces


def _chunk_section(section: _Section) -> list[tuple[list[str], str]]:
    """Accumulate a section's pieces into (heading_path, content) chunks, respecting target/max/overlap."""
    chunks: list[tuple[list[str], str]] = []
    current_words: list[str] = []

    def flush(*, keep_overlap: bool) -> None:
        nonlocal current_words
        if current_words:
            chunks.append((section.heading_path, " ".join(current_words)))
            current_words = current_words[-_OVERLAP_WORDS:] if keep_overlap else []

    for piece in _section_pieces(section):
        if current_words and len(current_words) + len(piece) > _MAX_WORDS:
            flush(keep_overlap=True)
        current_words.extend(piece)
        if len(current_words) >= _TARGET_WORDS:
            flush(keep_overlap=True)
    flush(keep_overlap=False)
    return chunks


class HeadingAwareWordChunker:
    """Deterministic chunker: preserves Markdown heading hierarchy, targets ~350 words/chunk."""

    chunking_version = CHUNKING_VERSION

    def chunk(
        self, *, document: KnowledgeDocument, chunking_version: str = CHUNKING_VERSION
    ) -> list[KnowledgeChunk]:
        sections = _split_into_sections(document.content_text)
        raw_chunks: list[tuple[list[str], str]] = []
        for section in sections:
            raw_chunks.extend(_chunk_section(section))

        result: list[KnowledgeChunk] = []
        for index, (heading_path, content) in enumerate(raw_chunks):
            stripped = content.strip()
            if not stripped:
                continue
            word_count = len(stripped.split())
            result.append(
                KnowledgeChunk(
                    document_id=document.document_id,
                    chunk_index=index,
                    heading_path=heading_path,
                    content=stripped,
                    content_hash=hashlib.sha256(stripped.encode("utf-8")).hexdigest(),
                    word_count=word_count,
                    estimated_token_count=max(1, round(word_count * _TOKENS_PER_WORD)),
                    available_at=document.available_at,
                    effective_until=document.effective_until,
                    chunking_version=chunking_version,
                )
            )
        return result
