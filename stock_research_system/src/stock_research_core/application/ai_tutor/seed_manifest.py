"""Seed-knowledge manifest model, loader, and source-file contract helpers.

Loads and validates `knowledge/seed_documents/manifest.json` (schema
version, expected collection/language, `document_count`, per-document
uniqueness and path safety) and the restricted YAML-subset front matter
each manifest-tracked Markdown file carries, per the C3 spec. No
boto3, SQLAlchemy, or `KnowledgeIngestionService` import here - this
module only ever validates already-read bytes/text; the actual S3 and
database orchestration lives in `manifest_ingestion.py`.

Two distinct hashes matter and must never be conflated:

- `manifest_file_hash` (this module's `compute_manifest_file_hash`):
  SHA-256 over the *complete* canonical source file, front matter
  included - matches `manifest.json`'s `content_hash` and is what gets
  stored as S3 object metadata.
- `parsed_content_hash`: computed separately by the existing
  `infrastructure.ai_tutor.local_document_parsers.parse_local_document`
  over the normalized *body* text actually ingested (front matter
  stripped) - becomes `KnowledgeDocument.content_hash`. This module
  never computes that hash; it only produces the stripped body that
  gets handed to the parser.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from stock_research_core.application.exceptions import SeedManifestValidationError

SUPPORTED_MANIFEST_VERSIONS: tuple[int, ...] = (1,)
DEFAULT_EXPECTED_COLLECTION = "finquest_core_financial_education"
DEFAULT_EXPECTED_LANGUAGE = "en"

APPROVED_SEED_REVIEW_STATUS = "approved_seed"
RECOGNIZED_REVIEW_STATUSES: frozenset[str] = frozenset(
    {APPROVED_SEED_REVIEW_STATUS, "draft_requires_source_review", "rejected"}
)

_REQUIRED_ENTRY_FIELDS = ("document_id", "filename", "title", "review_status", "content_hash")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_DRIVE_LETTER_RE = re.compile(r"^[A-Za-z]:")

_REQUIRED_FRONT_MATTER_FIELDS = ("document_id", "title", "language", "review_status", "version")
_FRONT_MATTER_KEY_RE = re.compile(r"[a-z_][a-z0-9_]*")


# -- manifest model -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SeedManifestDocument:
    """One validated entry from `manifest.json`."""

    document_id: str
    filename: str
    title: str
    review_status: str
    content_hash: str
    slug: str | None = None
    difficulty: tuple[str, ...] = field(default_factory=tuple)
    concept_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_approved_seed(self) -> bool:
        return self.review_status == APPROVED_SEED_REVIEW_STATUS


@dataclass(frozen=True, slots=True)
class SeedManifest:
    """A fully validated seed-knowledge manifest."""

    collection: str
    version: int
    language: str
    document_count: int
    documents: tuple[SeedManifestDocument, ...]

    def get(self, document_id: str) -> SeedManifestDocument | None:
        for document in self.documents:
            if document.document_id == document_id:
                return document
        return None

    def approved_documents(self) -> tuple[SeedManifestDocument, ...]:
        return tuple(document for document in self.documents if document.is_approved_seed)


# -- path safety ----------------------------------------------------------------------------------


def _validate_manifest_filename(filename: str, *, language: str) -> None:
    """Reject unsafe manifest filenames (structural check only - no filesystem access).

    `PurePosixPath.parts` silently collapses doubled slashes (`a//b` ->
    `('a', 'b')`), which would hide an empty path segment - so empty/'.'/'..'
    segments are checked via a manual split on the raw string first, and
    `PurePosixPath` is used afterwards only for the absolute-path check.
    """
    if not filename:
        raise SeedManifestValidationError("filename must be non-empty")
    if "\\" in filename:
        raise SeedManifestValidationError(f"filename {filename!r} must not contain backslashes")
    if _CONTROL_CHAR_RE.search(filename):
        raise SeedManifestValidationError(f"filename {filename!r} must not contain control characters")
    if filename.startswith("/") or _DRIVE_LETTER_RE.match(filename):
        raise SeedManifestValidationError(f"filename {filename!r} must be a relative POSIX-style path")

    segments = filename.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise SeedManifestValidationError(
            f"filename {filename!r} must not contain empty, '.', or '..' path segments"
        )

    if PurePosixPath(filename).is_absolute():
        raise SeedManifestValidationError(f"filename {filename!r} must be a relative path")

    if segments[0] != language:
        raise SeedManifestValidationError(
            f"filename {filename!r} must live under the manifest's language directory '{language}/'"
        )


def resolve_document_path(seed_documents_root: Path, filename: str, *, language: str) -> Path:
    """Validate `filename` and resolve it to an absolute path guaranteed to
    stay inside `seed_documents_root` (final resolved-path containment check)."""
    _validate_manifest_filename(filename, language=language)

    root_resolved = seed_documents_root.resolve()
    candidate = (seed_documents_root / filename).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise SeedManifestValidationError(
            f"resolved path for filename {filename!r} escapes seed-documents root '{seed_documents_root}'"
        )
    return candidate


# -- manifest loading -------------------------------------------------------------------------------


def _require_str(entry: dict[str, Any], field_name: str, *, context: str) -> str:
    value = entry.get(field_name)
    if not isinstance(value, str) or not value:
        raise SeedManifestValidationError(f"{context}: {field_name!r} must be a non-empty string")
    return value


def _parse_entry(entry: dict[str, Any], *, index: int, language: str) -> SeedManifestDocument:
    context = f"documents[{index}]"
    if not isinstance(entry, dict):
        raise SeedManifestValidationError(f"{context} must be a JSON object")

    for required_field in _REQUIRED_ENTRY_FIELDS:
        if required_field not in entry:
            raise SeedManifestValidationError(f"{context} is missing required field {required_field!r}")

    document_id = _require_str(entry, "document_id", context=context)
    filename = _require_str(entry, "filename", context=context)
    title = _require_str(entry, "title", context=context)
    review_status = _require_str(entry, "review_status", context=context)
    content_hash = _require_str(entry, "content_hash", context=context)

    if review_status not in RECOGNIZED_REVIEW_STATUSES:
        raise SeedManifestValidationError(
            f"{context}: unrecognized review_status {review_status!r} "
            f"(recognized: {sorted(RECOGNIZED_REVIEW_STATUSES)})"
        )

    normalized_hash = content_hash.strip().lower()
    if not _SHA256_HEX_RE.fullmatch(normalized_hash):
        raise SeedManifestValidationError(
            f"{context}: content_hash must be exactly 64 lowercase hexadecimal characters"
        )
    if normalized_hash != content_hash:
        raise SeedManifestValidationError(f"{context}: content_hash must already be lowercase hexadecimal")

    _validate_manifest_filename(filename, language=language)

    slug = entry.get("slug")
    if slug is not None and (not isinstance(slug, str) or not slug):
        raise SeedManifestValidationError(f"{context}: slug must be a non-empty string when present")

    difficulty_raw = entry.get("difficulty", [])
    if not isinstance(difficulty_raw, list) or not all(isinstance(item, str) for item in difficulty_raw):
        raise SeedManifestValidationError(f"{context}: difficulty must be a list of strings")

    concept_ids_raw = entry.get("concept_ids", [])
    if not isinstance(concept_ids_raw, list) or not all(isinstance(item, str) for item in concept_ids_raw):
        raise SeedManifestValidationError(f"{context}: concept_ids must be a list of strings")

    return SeedManifestDocument(
        document_id=document_id,
        filename=filename,
        title=title,
        review_status=review_status,
        content_hash=normalized_hash,
        slug=slug,
        difficulty=tuple(difficulty_raw),
        concept_ids=tuple(concept_ids_raw),
    )


def load_seed_manifest(
    manifest_path: Path,
    *,
    seed_documents_root: Path | None = None,
    expected_collection: str = DEFAULT_EXPECTED_COLLECTION,
    expected_language: str = DEFAULT_EXPECTED_LANGUAGE,
) -> SeedManifest:
    """Load and fully validate a seed-knowledge manifest from `manifest_path`.

    `seed_documents_root` (defaulting to `manifest_path.parent`) is used
    only for the resolved-path containment check on each document's
    `filename` - no file is opened here.
    """
    try:
        raw_text = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SeedManifestValidationError(f"could not read manifest at '{manifest_path}': {exc}") from exc

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise SeedManifestValidationError(f"manifest at '{manifest_path}' is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise SeedManifestValidationError("manifest must be a JSON object")

    version = data.get("version")
    if version not in SUPPORTED_MANIFEST_VERSIONS:
        raise SeedManifestValidationError(
            f"unsupported manifest version {version!r} (supported: {SUPPORTED_MANIFEST_VERSIONS})"
        )

    collection = data.get("collection")
    if collection != expected_collection:
        raise SeedManifestValidationError(
            f"unexpected manifest collection {collection!r} (expected {expected_collection!r})"
        )

    language = data.get("language")
    if language != expected_language:
        raise SeedManifestValidationError(
            f"unexpected manifest language {language!r} (expected {expected_language!r})"
        )

    documents_raw = data.get("documents")
    if not isinstance(documents_raw, list):
        raise SeedManifestValidationError("manifest 'documents' must be a list")

    document_count = data.get("document_count")
    if document_count != len(documents_raw):
        raise SeedManifestValidationError(
            f"manifest document_count ({document_count!r}) does not match "
            f"the number of document entries ({len(documents_raw)})"
        )

    documents = tuple(
        _parse_entry(entry, index=index, language=language) for index, entry in enumerate(documents_raw)
    )

    _validate_uniqueness(documents)

    root = seed_documents_root if seed_documents_root is not None else manifest_path.parent
    for document in documents:
        resolve_document_path(root, document.filename, language=language)

    return SeedManifest(
        collection=collection,
        version=version,
        language=language,
        document_count=document_count,
        documents=documents,
    )


def _validate_uniqueness(documents: tuple[SeedManifestDocument, ...]) -> None:
    seen_ids: set[str] = set()
    seen_filenames: set[str] = set()
    seen_slugs: set[str] = set()

    for document in documents:
        if document.document_id in seen_ids:
            raise SeedManifestValidationError(f"duplicate document_id {document.document_id!r}")
        seen_ids.add(document.document_id)

        if document.filename in seen_filenames:
            raise SeedManifestValidationError(f"duplicate filename {document.filename!r}")
        seen_filenames.add(document.filename)

        if document.slug is not None:
            if document.slug in seen_slugs:
                raise SeedManifestValidationError(f"duplicate slug {document.slug!r}")
            seen_slugs.add(document.slug)


# -- canonical source-file hashing -----------------------------------------------------------------


def canonicalize_source_text(raw_bytes: bytes) -> bytes:
    """Canonical UTF-8 with CRLF/CR normalized to LF - the exact byte
    sequence `manifest_file_hash` is computed over and what gets stored
    in object storage."""
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SeedManifestValidationError(f"source file is not valid UTF-8: {exc}") from exc
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.encode("utf-8")


def compute_manifest_file_hash(canonical_bytes: bytes) -> str:
    return sha256(canonical_bytes).hexdigest()


# -- restricted front-matter parsing ----------------------------------------------------------------
#
# Deliberately not full YAML: only top-level `key: value` scalars and
# top-level `key:` + indented `  - item` lists are understood, matching
# the same restricted subset `scripts/validate_seed_knowledge.py` already
# authors these files against. No third-party YAML parser is a project
# dependency, and a restricted grammar is also simply safer to parse than
# arbitrary YAML for content whose origin is a content-authoring pipeline.


@dataclass(frozen=True, slots=True)
class ParsedFrontMatter:
    document_id: str
    title: str
    language: str
    review_status: str
    version: int
    raw: dict[str, Any]


def _parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if value == "null":
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    if value == "[]":
        return []
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def parse_restricted_front_matter(front_matter_text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_list_key: str | None = None

    for line_number, line in enumerate(front_matter_text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        if line.startswith("  - "):
            if current_list_key is None:
                raise SeedManifestValidationError(f"front matter line {line_number}: list item without a list key")
            result[current_list_key].append(_parse_scalar(line[4:]))
            continue

        if line.startswith((" ", "\t")):
            raise SeedManifestValidationError(f"front matter line {line_number}: unsupported nested YAML")

        if ":" not in line:
            raise SeedManifestValidationError(f"front matter line {line_number}: expected 'key: value'")

        key, raw_value = line.split(":", 1)
        key = key.strip()
        if not _FRONT_MATTER_KEY_RE.fullmatch(key):
            raise SeedManifestValidationError(f"front matter line {line_number}: invalid key {key!r}")

        raw_value = raw_value.strip()
        if not raw_value:
            result[key] = []
            current_list_key = key
        else:
            result[key] = _parse_scalar(raw_value)
            current_list_key = None

    return result


def split_front_matter(source_text: str) -> tuple[str, str]:
    """Split canonical source text into (front_matter_text, body_markdown).

    `body_markdown` is everything after the closing `---` delimiter,
    with leading blank lines stripped so it begins at the document's H1.
    """
    if not source_text.startswith("---\n"):
        raise SeedManifestValidationError("source file must begin with a YAML front-matter block ('---')")

    closing_index = source_text.find("\n---\n", 4)
    if closing_index < 0:
        raise SeedManifestValidationError("front-matter block is not terminated with a closing '---'")

    front_matter_text = source_text[4:closing_index]
    body = source_text[closing_index + len("\n---\n") :].lstrip("\n")
    return front_matter_text, body


def parse_and_validate_front_matter(
    source_text: str,
    *,
    manifest_document: SeedManifestDocument,
    expected_language: str,
) -> tuple[ParsedFrontMatter, str]:
    """Split, parse, and cross-check one document's front matter against
    the manifest/source contract. Returns `(parsed_front_matter, body)`,
    where `body` is the Markdown beginning with the document's H1 -
    exactly what must be handed to `KnowledgeIngestionService`."""
    front_matter_text, body = split_front_matter(source_text)
    raw = parse_restricted_front_matter(front_matter_text)

    missing = [name for name in _REQUIRED_FRONT_MATTER_FIELDS if name not in raw or raw[name] in (None, "")]
    if missing:
        raise SeedManifestValidationError(f"front matter is missing required field(s): {missing}")

    version_raw = raw["version"]
    if not isinstance(version_raw, int) or isinstance(version_raw, bool) or version_raw < 1:
        raise SeedManifestValidationError(f"front matter 'version' must be a positive integer, got {version_raw!r}")

    parsed = ParsedFrontMatter(
        document_id=str(raw["document_id"]),
        title=str(raw["title"]),
        language=str(raw["language"]),
        review_status=str(raw["review_status"]),
        version=version_raw,
        raw=raw,
    )

    if parsed.document_id != manifest_document.document_id:
        raise SeedManifestValidationError(
            f"front matter document_id {parsed.document_id!r} does not match "
            f"manifest document_id {manifest_document.document_id!r}"
        )
    if parsed.title != manifest_document.title:
        raise SeedManifestValidationError(
            f"front matter title {parsed.title!r} does not match manifest title {manifest_document.title!r}"
        )
    if parsed.language != expected_language:
        raise SeedManifestValidationError(
            f"front matter language {parsed.language!r} does not match manifest language {expected_language!r}"
        )
    if parsed.review_status != manifest_document.review_status:
        raise SeedManifestValidationError(
            f"front matter review_status {parsed.review_status!r} does not match "
            f"manifest review_status {manifest_document.review_status!r}"
        )

    if not body.strip():
        raise SeedManifestValidationError("document body is empty after stripping front matter")
    if not body.lstrip().startswith("#"):
        raise SeedManifestValidationError("document body must begin with an H1 heading")

    return parsed, body
