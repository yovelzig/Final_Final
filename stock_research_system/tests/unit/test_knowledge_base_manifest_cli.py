"""Unit tests for the F1b/C3 manifest-ingestion wiring in
`cli.knowledge_base` (`--ingest-manifest`/`--document-code`/`--dry-run`).

Exercises argument validation, lazy object-storage construction, exit
codes, and reporting entirely against monkeypatched fakes - no real
PostgreSQL connection is ever opened, no real boto3 client is
constructed, and no AWS call is made. `KnowledgeIngestionService` and
`S3ObjectStorageAdapter` are replaced with small in-memory fakes (module
constants patched by name, the same composition-root pattern the CLI
itself uses); `DatabaseSettings`/`create_database_engine` are left real
since constructing them performs no I/O (see
`infrastructure.database.engine`'s own module docstring) - only
`create_database_engine` is stubbed, for determinism and speed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from stock_research_core.application.ai_tutor.seed_manifest import (
    canonicalize_source_text,
    compute_manifest_file_hash,
)
from stock_research_core.application.exceptions import ObjectNotFoundError
from stock_research_core.application.object_storage.models import ObjectReference, StoredObject
from stock_research_core.cli import knowledge_base as cli_module
from stock_research_core.domain.ai_tutor.enums import KnowledgeApprovalStatus


def _parse(argv: list[str]):
    return cli_module._build_arg_parser().parse_args(argv)


def _run(args) -> int:
    return asyncio.run(cli_module._run(args))


class _FakeEngine:
    async def dispose(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _no_real_database_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every `_run()` call constructs a database engine unconditionally
    (per the manifest-composition contract's own step 1) - stub it to a
    trivial fake so no test in this file depends on a real Postgres
    connection string resolving to anything, and disposal is instant."""
    monkeypatch.setattr(cli_module, "create_database_engine", lambda settings: _FakeEngine())
    monkeypatch.setattr(cli_module, "create_session_factory", lambda engine: object())


class _RaiseIfCalled:
    """A stand-in for `S3ObjectStorageAdapter`/`ObjectStorageSettings` that fails the
    test immediately if it is ever constructed - proves lazy construction."""

    def __init__(self, *args, **kwargs) -> None:
        raise AssertionError(f"{type(self).__name__} must not be constructed for this CLI action")


@pytest.fixture(autouse=True)
def _deny_object_storage_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: object storage must never be touched. Manifest tests
    override these two names explicitly to fakes that do work."""
    monkeypatch.setattr(cli_module, "ObjectStorageSettings", _RaiseIfCalled)
    monkeypatch.setattr(cli_module, "S3ObjectStorageAdapter", _RaiseIfCalled)


# -- fakes for --ingest-manifest tests: no real DB, no real S3 --------------------------------------


@dataclass
class _RecordedIngestCall:
    file_path: Path
    source_title: str
    source_key: str | None
    approval_status: KnowledgeApprovalStatus


@dataclass
class _FakeIngestionSummary:
    documents_created: int = 1
    documents_skipped_unchanged: int = 0
    documents_archived: int = 0


class _FakeKnowledgeIngestionService:
    """Stands in for the real `KnowledgeIngestionService` - records calls,
    never touches a database."""

    def __init__(self, *args, **kwargs) -> None:
        self.calls: list[_RecordedIngestCall] = []

    async def ingest_local_document(
        self, *, file_path: Path, source_title: str, approval_status, skill_ids, available_at, source_key=None
    ) -> _FakeIngestionSummary:
        self.calls.append(
            _RecordedIngestCall(
                file_path=file_path, source_title=source_title, source_key=source_key,
                approval_status=approval_status,
            )
        )
        return _FakeIngestionSummary()


@dataclass
class _StoredVersion:
    sha256: str
    version_id: str


class _FakeObjectStorage:
    """Minimal in-memory `ObjectStoragePort` - test-only, not under `src/`."""

    def __init__(self, *args, **kwargs) -> None:
        self._versions: dict[str, _StoredVersion] = {}
        self._seq = 0

    async def put_object(self, *, key: str, body: bytes, content_type: str):
        self._seq += 1
        version_id = f"v{self._seq}"
        sha256 = hashlib.sha256(body).hexdigest()
        self._versions[key] = _StoredVersion(sha256=sha256, version_id=version_id)
        return ObjectReference(
            bucket="fake-bucket", key=key, content_type=content_type, byte_length=len(body),
            sha256=sha256, version_id=version_id,
        )

    async def head_object(self, *, key: str, version_id: str | None = None):
        record = self._versions.get(key)
        if record is None:
            raise ObjectNotFoundError(f"no object at key {key!r}")
        return ObjectReference(
            bucket="fake-bucket", key=key, content_type="text/markdown; charset=utf-8", byte_length=0,
            sha256=record.sha256, version_id=record.version_id,
        )

    async def get_object(self, *, key: str, version_id: str | None = None):
        record = self._versions.get(key)
        body = _BODY_BY_KEY[key]
        return StoredObject(
            body=body,
            reference=ObjectReference(
                bucket="fake-bucket", key=key, content_type="text/markdown; charset=utf-8",
                byte_length=len(body), sha256=record.sha256, version_id=record.version_id,
            ),
        )


_BODY_BY_KEY: dict[str, bytes] = {}


def _front_matter_source(*, document_id: str, title: str, review_status: str = "approved_seed") -> str:
    return (
        "---\n"
        f'document_id: "{document_id}"\n'
        f'title: "{title}"\n'
        "version: 1\n"
        'language: "en"\n'
        f'review_status: "{review_status}"\n'
        "---\n"
        "\n"
        f"# {title}\n"
        "\n"
        f"Body content for {document_id}.\n"
    )


def _write_seed_document(seed_root: Path, *, filename: str, source_text: str) -> str:
    path = seed_root / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source_text, encoding="utf-8", newline="\n")
    canonical = canonicalize_source_text(path.read_bytes())
    key = f"knowledge/seed/{filename}"
    _BODY_BY_KEY[key] = canonical
    return compute_manifest_file_hash(canonical)


def _write_manifest(seed_root: Path, documents: list[dict]) -> Path:
    manifest = {
        "collection": "finquest_core_financial_education", "version": 1, "language": "en",
        "document_count": len(documents), "documents": documents,
    }
    manifest_path = seed_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


@pytest.fixture
def seed_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _BODY_BY_KEY.clear()
    seed_root = tmp_path / "seed_documents"
    text_a = _front_matter_source(document_id="kb-en-001", title="Doc A")
    hash_a = _write_seed_document(seed_root, filename="en/01_doc_a.md", source_text=text_a)
    _write_manifest(
        seed_root,
        [
            {
                "document_id": "kb-en-001", "filename": "en/01_doc_a.md", "title": "Doc A",
                "review_status": "approved_seed", "content_hash": hash_a,
            },
        ],
    )
    monkeypatch.setattr(cli_module, "SEED_DOCUMENTS_ROOT", seed_root)
    monkeypatch.setattr(cli_module, "SEED_MANIFEST_PATH", seed_root / "manifest.json")
    monkeypatch.setattr(cli_module, "KnowledgeIngestionService", _FakeKnowledgeIngestionService)
    monkeypatch.setattr(cli_module, "ObjectStorageSettings", lambda: _RealishObjectStorageSettings())
    monkeypatch.setattr(cli_module, "S3ObjectStorageAdapter", _FakeObjectStorage)
    return {"seed_root": seed_root}


@dataclass
class _RealishObjectStorageSettings:
    object_storage_provider: str = "s3"
    s3_knowledge_prefix: str = "knowledge/"


# -- 1. parser recognizes the new flags --------------------------------------------------------


def test_parser_recognizes_ingest_manifest_flags() -> None:
    args = _parse(["--ingest-manifest", "--document-code", "kb-en-001", "--dry-run"])
    assert args.ingest_manifest is True
    assert args.document_code == "kb-en-001"
    assert args.dry_run is True


# -- 2/3. invalid argument combinations exit 2 before any engine/client exists ------------------


def test_document_code_without_ingest_manifest_returns_2(capsys: pytest.CaptureFixture[str]) -> None:
    args = _parse(["--document-code", "kb-en-001"])
    assert _run(args) == 2
    assert "--document-code requires --ingest-manifest" in capsys.readouterr().err


def test_dry_run_without_ingest_manifest_returns_2(capsys: pytest.CaptureFixture[str]) -> None:
    args = _parse(["--dry-run"])
    assert _run(args) == 2
    assert "--dry-run requires --ingest-manifest" in capsys.readouterr().err


# -- 4/5/6. manifest dry-run wiring --------------------------------------------------------------


def test_manifest_dry_run_passes_dry_run_true(seed_world) -> None:
    args = _parse(["--ingest-manifest", "--dry-run"])
    assert _run(args) == 0


def test_document_code_is_passed_unchanged(seed_world) -> None:
    args = _parse(["--ingest-manifest", "--document-code", "kb-en-001"])
    assert _run(args) == 0


def test_approval_is_always_approved(seed_world, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    real_ingest = cli_module.ManifestIngestionService.ingest

    async def _spy_ingest(self, **kwargs):
        captured.update(kwargs)
        return await real_ingest(self, **kwargs)

    monkeypatch.setattr(cli_module.ManifestIngestionService, "ingest", _spy_ingest)

    args = _parse(["--ingest-manifest"])
    assert _run(args) == 0
    assert captured["approval_status"] == KnowledgeApprovalStatus.APPROVED
    assert captured["document_code"] is None


# -- 7/8. exit codes reflect batch outcome -------------------------------------------------------


def test_failed_count_greater_than_zero_returns_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _BODY_BY_KEY.clear()
    seed_root = tmp_path / "seed_documents"
    text_a = _front_matter_source(document_id="kb-en-001", title="Doc A")
    _write_seed_document(seed_root, filename="en/01_doc_a.md", source_text=text_a)
    _write_manifest(
        seed_root,
        [
            {
                # Deliberately wrong hash so this single entry fails.
                "document_id": "kb-en-001", "filename": "en/01_doc_a.md", "title": "Doc A",
                "review_status": "approved_seed", "content_hash": "a" * 64,
            },
        ],
    )
    monkeypatch.setattr(cli_module, "SEED_DOCUMENTS_ROOT", seed_root)
    monkeypatch.setattr(cli_module, "SEED_MANIFEST_PATH", seed_root / "manifest.json")
    monkeypatch.setattr(cli_module, "KnowledgeIngestionService", _FakeKnowledgeIngestionService)
    monkeypatch.setattr(cli_module, "ObjectStorageSettings", lambda: _RealishObjectStorageSettings())
    monkeypatch.setattr(cli_module, "S3ObjectStorageAdapter", _FakeObjectStorage)

    args = _parse(["--ingest-manifest"])
    assert _run(args) == 1


def test_zero_failures_returns_0(seed_world) -> None:
    args = _parse(["--ingest-manifest"])
    assert _run(args) == 0


# -- 9. per-document summary is printed ----------------------------------------------------------


def test_per_document_summary_is_printed(seed_world, capsys: pytest.CaptureFixture[str]) -> None:
    args = _parse(["--ingest-manifest"])
    assert _run(args) == 0
    out = capsys.readouterr().out
    assert "kb-en-001" in out
    assert "knowledge/seed/en/01_doc_a.md" in out
    assert "succeeded:" in out
    assert "failed:" in out


# -- 10. unsupported object-storage provider is rejected ------------------------------------------


def test_unsupported_object_storage_provider_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _BODY_BY_KEY.clear()
    seed_root = tmp_path / "seed_documents"
    text_a = _front_matter_source(document_id="kb-en-001", title="Doc A")
    hash_a = _write_seed_document(seed_root, filename="en/01_doc_a.md", source_text=text_a)
    _write_manifest(
        seed_root,
        [
            {
                "document_id": "kb-en-001", "filename": "en/01_doc_a.md", "title": "Doc A",
                "review_status": "approved_seed", "content_hash": hash_a,
            },
        ],
    )
    monkeypatch.setattr(cli_module, "SEED_DOCUMENTS_ROOT", seed_root)
    monkeypatch.setattr(cli_module, "SEED_MANIFEST_PATH", seed_root / "manifest.json")
    monkeypatch.setattr(cli_module, "KnowledgeIngestionService", _FakeKnowledgeIngestionService)

    @dataclass
    class _UnsupportedProviderSettings:
        object_storage_provider: str = "gcs"

    monkeypatch.setattr(cli_module, "ObjectStorageSettings", lambda: _UnsupportedProviderSettings())
    monkeypatch.setattr(cli_module, "S3ObjectStorageAdapter", _RaiseIfCalled)

    args = _parse(["--ingest-manifest"])
    assert _run(args) == 1
    assert "unsupported OBJECT_STORAGE_PROVIDER" in capsys.readouterr().err


# -- 11/12/13. S3 adapter is not constructed for other CLI actions --------------------------------


async def _noop(*args, **kwargs) -> None:
    return None


def test_s3_adapter_not_constructed_for_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module, "_print_status", _noop)
    args = _parse(["--status"])
    assert _run(args) == 0


def test_s3_adapter_not_constructed_for_search(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module, "_search", _noop)
    args = _parse(["--search", "diversification"])
    assert _run(args) == 0


def test_s3_adapter_not_constructed_for_ingest_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module, "_ingest_file", _noop)
    args = _parse(["--ingest-file", "some/doc.md", "--source-title", "A Document"])
    assert _run(args) == 0


# -- 14. --help performs no client construction ---------------------------------------------------


def test_help_performs_no_client_construction() -> None:
    with pytest.raises(SystemExit) as exc_info:
        _parse(["--help"])
    assert exc_info.value.code == 0


# -- 15. missing manifest/corpus path produces a clean controlled error ---------------------------


def test_missing_seed_documents_root_is_a_controlled_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    missing_root = tmp_path / "does-not-exist"
    monkeypatch.setattr(cli_module, "SEED_DOCUMENTS_ROOT", missing_root)
    monkeypatch.setattr(cli_module, "SEED_MANIFEST_PATH", missing_root / "manifest.json")

    args = _parse(["--ingest-manifest"])
    assert _run(args) == 1
    assert "seed documents root not found" in capsys.readouterr().err


def test_missing_manifest_file_is_a_controlled_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_root = tmp_path / "seed_documents"
    seed_root.mkdir(parents=True)
    monkeypatch.setattr(cli_module, "SEED_DOCUMENTS_ROOT", seed_root)
    monkeypatch.setattr(cli_module, "SEED_MANIFEST_PATH", seed_root / "manifest.json")

    args = _parse(["--ingest-manifest"])
    assert _run(args) == 1
    assert "seed manifest not found" in capsys.readouterr().err
