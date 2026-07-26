"""Unit tests for the C3 seed-manifest model, loader, path-safety
validation, and restricted front-matter parsing.

Pure filesystem/string tests - no PostgreSQL, no object storage, no
`KnowledgeIngestionService`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from stock_research_core.application.ai_tutor.seed_manifest import (
    APPROVED_SEED_REVIEW_STATUS,
    SeedManifestDocument,
    canonicalize_source_text,
    compute_manifest_file_hash,
    load_seed_manifest,
    parse_and_validate_front_matter,
    resolve_document_path,
    split_front_matter,
)
from stock_research_core.application.exceptions import SeedManifestValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_MANIFEST_PATH = REPO_ROOT / "knowledge" / "seed_documents" / "manifest.json"
REAL_SEED_DOCUMENTS_ROOT = REPO_ROOT / "knowledge" / "seed_documents"

_VALID_HASH = "a" * 64


def _manifest_dict(**overrides: object) -> dict:
    base = {
        "collection": "finquest_core_financial_education",
        "version": 1,
        "language": "en",
        "document_count": 1,
        "documents": [
            {
                "document_id": "kb-en-001",
                "filename": "en/01_doc.md",
                "title": "Doc One",
                "slug": "doc-one",
                "review_status": "approved_seed",
                "content_hash": _VALID_HASH,
            }
        ],
    }
    base.update(overrides)
    return base


def _write_manifest(tmp_path: Path, manifest: dict) -> Path:
    seed_root = tmp_path / "seed_documents"
    (seed_root / "en").mkdir(parents=True, exist_ok=True)
    manifest_path = seed_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


_SAMPLE_SOURCE = (
    "---\n"
    'document_id: "kb-en-001"\n'
    'title: "Doc One"\n'
    "version: 1\n"
    'language: "en"\n'
    'review_status: "approved_seed"\n'
    "difficulty:\n"
    '  - "beginner"\n'
    "lesson_ids: []\n"
    "---\n"
    "\n"
    "# Doc One\n"
    "\n"
    "Body content here.\n"
)


# -- load_seed_manifest: happy path -----------------------------------------------------------------


def test_real_seed_manifest_loads_and_validates() -> None:
    manifest = load_seed_manifest(REAL_MANIFEST_PATH)
    assert manifest.collection == "finquest_core_financial_education"
    assert manifest.language == "en"
    assert manifest.document_count == 15
    assert len(manifest.documents) == 15
    assert all(document.is_approved_seed for document in manifest.documents)
    assert manifest.get("kb-en-001") is not None
    assert manifest.get("kb-en-999") is None
    assert len(manifest.approved_documents()) == 15


def test_load_seed_manifest_happy_path(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, _manifest_dict())
    (manifest_path.parent / "en" / "01_doc.md").write_text("placeholder", encoding="utf-8")

    manifest = load_seed_manifest(manifest_path)

    assert manifest.version == 1
    assert manifest.documents[0].document_id == "kb-en-001"
    assert manifest.documents[0].slug == "doc-one"


# -- load_seed_manifest: top-level validation --------------------------------------------------------


def test_unsupported_manifest_version_is_rejected(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, _manifest_dict(version=99))
    with pytest.raises(SeedManifestValidationError, match="unsupported manifest version"):
        load_seed_manifest(manifest_path)


def test_unexpected_collection_is_rejected(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, _manifest_dict(collection="something_else"))
    with pytest.raises(SeedManifestValidationError, match="unexpected manifest collection"):
        load_seed_manifest(manifest_path)


def test_unexpected_language_is_rejected(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, _manifest_dict(language="fr"))
    with pytest.raises(SeedManifestValidationError, match="unexpected manifest language"):
        load_seed_manifest(manifest_path)


def test_document_count_mismatch_is_rejected(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, _manifest_dict(document_count=2))
    with pytest.raises(SeedManifestValidationError, match="document_count"):
        load_seed_manifest(manifest_path)


def test_malformed_json_is_rejected(tmp_path: Path) -> None:
    seed_root = tmp_path / "seed_documents"
    seed_root.mkdir(parents=True)
    manifest_path = seed_root / "manifest.json"
    manifest_path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(SeedManifestValidationError, match="not valid JSON"):
        load_seed_manifest(manifest_path)


# -- load_seed_manifest: per-entry validation --------------------------------------------------------


@pytest.mark.parametrize("missing_field", ["document_id", "filename", "title", "review_status", "content_hash"])
def test_missing_required_entry_field_is_rejected(tmp_path: Path, missing_field: str) -> None:
    manifest = _manifest_dict()
    del manifest["documents"][0][missing_field]
    manifest_path = _write_manifest(tmp_path, manifest)
    with pytest.raises(SeedManifestValidationError):
        load_seed_manifest(manifest_path)


def test_duplicate_document_ids_are_rejected(tmp_path: Path) -> None:
    manifest = _manifest_dict()
    second = dict(manifest["documents"][0])
    second["filename"] = "en/02_doc.md"
    second["slug"] = "doc-two"
    manifest["documents"].append(second)
    manifest["document_count"] = 2
    manifest_path = _write_manifest(tmp_path, manifest)
    with pytest.raises(SeedManifestValidationError, match="duplicate document_id"):
        load_seed_manifest(manifest_path)


def test_duplicate_filenames_are_rejected(tmp_path: Path) -> None:
    manifest = _manifest_dict()
    second = dict(manifest["documents"][0])
    second["document_id"] = "kb-en-002"
    second["slug"] = "doc-two"
    manifest["documents"].append(second)
    manifest["document_count"] = 2
    manifest_path = _write_manifest(tmp_path, manifest)
    with pytest.raises(SeedManifestValidationError, match="duplicate filename"):
        load_seed_manifest(manifest_path)


def test_duplicate_slugs_are_rejected(tmp_path: Path) -> None:
    manifest = _manifest_dict()
    second = dict(manifest["documents"][0])
    second["document_id"] = "kb-en-002"
    second["filename"] = "en/02_doc.md"
    manifest["documents"].append(second)
    manifest["document_count"] = 2
    manifest_path = _write_manifest(tmp_path, manifest)
    with pytest.raises(SeedManifestValidationError, match="duplicate slug"):
        load_seed_manifest(manifest_path)


@pytest.mark.parametrize(
    "bad_hash",
    [
        "short",
        "g" * 64,  # not hex
        "A" * 64,  # uppercase
        "a" * 63,
        "a" * 65,
    ],
)
def test_invalid_content_hash_is_rejected(tmp_path: Path, bad_hash: str) -> None:
    manifest = _manifest_dict()
    manifest["documents"][0]["content_hash"] = bad_hash
    manifest_path = _write_manifest(tmp_path, manifest)
    with pytest.raises(SeedManifestValidationError):
        load_seed_manifest(manifest_path)


def test_unrecognized_review_status_is_rejected(tmp_path: Path) -> None:
    manifest = _manifest_dict()
    manifest["documents"][0]["review_status"] = "bogus_status"
    manifest_path = _write_manifest(tmp_path, manifest)
    with pytest.raises(SeedManifestValidationError, match="unrecognized review_status"):
        load_seed_manifest(manifest_path)


@pytest.mark.parametrize(
    "unsafe_filename",
    [
        "/etc/passwd",
        "C:/Windows/system32/config",
        "en\\01_doc.md",
        "en/../secrets.md",
        "en/./01_doc.md",
        "en//01_doc.md",
        "../en/01_doc.md",
        "fr/01_doc.md",  # outside the manifest's declared language directory
        "en/01_doc.md\x00",
    ],
)
def test_unsafe_filenames_are_rejected(tmp_path: Path, unsafe_filename: str) -> None:
    manifest = _manifest_dict()
    manifest["documents"][0]["filename"] = unsafe_filename
    manifest_path = _write_manifest(tmp_path, manifest)
    with pytest.raises(SeedManifestValidationError):
        load_seed_manifest(manifest_path)


# -- resolve_document_path -----------------------------------------------------------------------------


def test_resolve_document_path_returns_path_inside_root() -> None:
    resolved = resolve_document_path(REAL_SEED_DOCUMENTS_ROOT, "en/01_financial_foundations.md", language="en")
    assert resolved == (REAL_SEED_DOCUMENTS_ROOT / "en" / "01_financial_foundations.md").resolve()


# -- canonicalization and manifest_file_hash ------------------------------------------------------------


def test_canonicalize_source_text_normalizes_crlf_and_cr() -> None:
    lf = canonicalize_source_text(b"first\nsecond\n")
    crlf = canonicalize_source_text(b"first\r\nsecond\r\n")
    cr = canonicalize_source_text(b"first\rsecond\r")
    assert lf == crlf == cr == b"first\nsecond\n"


def test_manifest_file_hash_is_independent_of_line_ending_style() -> None:
    lf_hash = compute_manifest_file_hash(canonicalize_source_text(b"first line\nsecond line\n"))
    crlf_hash = compute_manifest_file_hash(canonicalize_source_text(b"first line\r\nsecond line\r\n"))
    assert lf_hash == crlf_hash


def test_manifest_file_hash_matches_all_real_seed_documents() -> None:
    manifest = load_seed_manifest(REAL_MANIFEST_PATH)
    for document in manifest.documents:
        path = resolve_document_path(REAL_SEED_DOCUMENTS_ROOT, document.filename, language=manifest.language)
        canonical = canonicalize_source_text(path.read_bytes())
        assert compute_manifest_file_hash(canonical) == document.content_hash


def test_canonicalize_source_text_rejects_invalid_utf8() -> None:
    with pytest.raises(SeedManifestValidationError):
        canonicalize_source_text(b"\xff\xfe\x00\x00not utf-8")


# -- front-matter stripping and parsing --------------------------------------------------------------


def test_split_front_matter_returns_body_starting_at_h1() -> None:
    front_matter_text, body = split_front_matter(_SAMPLE_SOURCE)
    assert 'document_id: "kb-en-001"' in front_matter_text
    assert body.startswith("# Doc One")


def test_split_front_matter_requires_opening_delimiter() -> None:
    with pytest.raises(SeedManifestValidationError, match="must begin with"):
        split_front_matter("# No front matter\nBody.\n")


def test_split_front_matter_requires_closing_delimiter() -> None:
    with pytest.raises(SeedManifestValidationError, match="closing"):
        split_front_matter("---\ndocument_id: \"x\"\n\n# Body\n")


def test_parse_and_validate_front_matter_strips_front_matter_keys_from_body() -> None:
    manifest_document = SeedManifestDocument(
        document_id="kb-en-001",
        filename="en/01_doc.md",
        title="Doc One",
        review_status="approved_seed",
        content_hash=_VALID_HASH,
    )
    parsed, body = parse_and_validate_front_matter(
        _SAMPLE_SOURCE, manifest_document=manifest_document, expected_language="en"
    )
    assert parsed.document_id == "kb-en-001"
    assert parsed.version == 1
    assert body.startswith("# Doc One")
    for forbidden in ("review_status:", "document_id:", "language:"):
        assert forbidden not in body


def test_parse_and_validate_front_matter_rejects_document_id_mismatch() -> None:
    manifest_document = SeedManifestDocument(
        document_id="kb-en-999",
        filename="en/01_doc.md",
        title="Doc One",
        review_status="approved_seed",
        content_hash=_VALID_HASH,
    )
    with pytest.raises(SeedManifestValidationError, match="document_id"):
        parse_and_validate_front_matter(_SAMPLE_SOURCE, manifest_document=manifest_document, expected_language="en")


def test_parse_and_validate_front_matter_rejects_title_mismatch() -> None:
    manifest_document = SeedManifestDocument(
        document_id="kb-en-001",
        filename="en/01_doc.md",
        title="A Different Title",
        review_status="approved_seed",
        content_hash=_VALID_HASH,
    )
    with pytest.raises(SeedManifestValidationError, match="title"):
        parse_and_validate_front_matter(_SAMPLE_SOURCE, manifest_document=manifest_document, expected_language="en")


def test_parse_and_validate_front_matter_rejects_review_status_mismatch() -> None:
    manifest_document = SeedManifestDocument(
        document_id="kb-en-001",
        filename="en/01_doc.md",
        title="Doc One",
        review_status="rejected",
        content_hash=_VALID_HASH,
    )
    with pytest.raises(SeedManifestValidationError, match="review_status"):
        parse_and_validate_front_matter(_SAMPLE_SOURCE, manifest_document=manifest_document, expected_language="en")


def test_parse_and_validate_front_matter_rejects_missing_required_field() -> None:
    source_without_version = _SAMPLE_SOURCE.replace("version: 1\n", "")
    manifest_document = SeedManifestDocument(
        document_id="kb-en-001",
        filename="en/01_doc.md",
        title="Doc One",
        review_status="approved_seed",
        content_hash=_VALID_HASH,
    )
    with pytest.raises(SeedManifestValidationError, match="missing required field"):
        parse_and_validate_front_matter(
            source_without_version, manifest_document=manifest_document, expected_language="en"
        )


def test_real_seed_documents_front_matter_round_trips() -> None:
    """Every real approved seed document's front matter parses and its body
    starts with the H1, with front-matter keys excluded from the body -
    this is the regression proof that ingestion never leaks front matter
    into stored chunks."""
    manifest = load_seed_manifest(REAL_MANIFEST_PATH)
    for document in manifest.documents:
        path = resolve_document_path(REAL_SEED_DOCUMENTS_ROOT, document.filename, language=manifest.language)
        source_text = canonicalize_source_text(path.read_bytes()).decode("utf-8")
        _parsed, body = parse_and_validate_front_matter(
            source_text, manifest_document=document, expected_language=manifest.language
        )
        assert body.lstrip().startswith("# ")
        for forbidden in ("review_status:", "concept_ids:", "source_policy:"):
            assert forbidden not in body


# -- distinct hash concept -------------------------------------------------------------------------


def test_manifest_file_hash_and_naive_body_hash_are_distinct_for_real_document() -> None:
    """`manifest_file_hash` covers the whole file (front matter included);
    a hash of just the body text is a different value - proof the two
    hashing surfaces are not accidentally the same computation."""
    manifest = load_seed_manifest(REAL_MANIFEST_PATH)
    document = manifest.documents[0]
    path = resolve_document_path(REAL_SEED_DOCUMENTS_ROOT, document.filename, language=manifest.language)
    canonical = canonicalize_source_text(path.read_bytes())
    manifest_file_hash = compute_manifest_file_hash(canonical)

    _parsed, body = parse_and_validate_front_matter(
        canonical.decode("utf-8"), manifest_document=document, expected_language=manifest.language
    )
    naive_body_hash = hashlib.sha256(body.strip().encode("utf-8")).hexdigest()

    assert manifest_file_hash == document.content_hash
    assert naive_body_hash != manifest_file_hash
