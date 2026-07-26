from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "validate_seed_knowledge.py"

spec = importlib.util.spec_from_file_location("validate_seed_knowledge", SCRIPT)
assert spec is not None and spec.loader is not None
validator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = validator
spec.loader.exec_module(validator)


def _copy_collection(tmp_path: Path) -> Path:
    shutil.copytree(REPO_ROOT / "knowledge", tmp_path / "knowledge")
    return tmp_path


def test_real_seed_collection_is_valid() -> None:
    assert validator.validate_collection(REPO_ROOT) == []


def test_require_approved_reports_each_non_approved_document() -> None:
    expected_paths: set[str] = set()

    for target in sorted(
        (
            REPO_ROOT
            / "knowledge"
            / "seed_documents"
            / "en"
        ).glob("*.md")
    ):
        metadata, _ = validator.split_front_matter(
            target.read_text(encoding="utf-8")
        )
        if metadata["review_status"] != "approved_seed":
            expected_paths.add(str(target))

    issues = validator.validate_collection(
        REPO_ROOT,
        require_approved=True,
    )

    actual_paths = {
        issue.path
        for issue in issues
        if issue.message == "document is not approved_seed"
    }

    assert actual_paths == expected_paths


def test_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    root = _copy_collection(tmp_path)
    target = root / "knowledge/seed_documents/en/01_financial_foundations.md"
    target.write_text(
        target.read_text(encoding="utf-8") + "\nMaterial edit.\n",
        encoding="utf-8",
    )

    issues = validator.validate_collection(root)

    assert any("hash mismatch" in issue.message for issue in issues)


def test_placeholder_in_approved_document_is_rejected(
    tmp_path: Path,
) -> None:
    root = _copy_collection(tmp_path)
    target = root / "knowledge/seed_documents/en/01_financial_foundations.md"
    text = target.read_text(encoding="utf-8")
    text = text.replace(
        'review_status: "draft_requires_source_review"',
        'review_status: "approved_seed"',
    )
    text = text.replace(
        "reviewed_at: null",
        'reviewed_at: "2026-07-26"',
    )
    text += "\nTODO\n"
    target.write_text(text, encoding="utf-8")

    validator.update_hashes(root)
    issues = validator.validate_collection(root)

    assert any(
        "forbidden placeholder marker: TODO" in issue.message
        for issue in issues
    )


def test_update_hashes_repairs_manifest_after_content_edit(
    tmp_path: Path,
) -> None:
    root = _copy_collection(tmp_path)
    target = (
        root
        / "knowledge/seed_documents/en/02_budgeting_and_emergency_funds.md"
    )
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\nAdditional reviewed sentence.\n",
        encoding="utf-8",
    )

    assert any(
        "hash mismatch" in issue.message
        for issue in validator.validate_collection(root)
    )

    validator.update_hashes(root)

    assert validator.validate_collection(root) == []

def test_hash_is_independent_of_line_ending_style(
    tmp_path: Path,
) -> None:
    lf_path = tmp_path / "lf.md"
    crlf_path = tmp_path / "crlf.md"

    lf_path.write_bytes(b"first line\nsecond line\n")
    crlf_path.write_bytes(b"first line\r\nsecond line\r\n")

    assert validator.sha256_file(lf_path) == validator.sha256_file(crlf_path)

def test_require_approved_rejects_a_draft_document(
    tmp_path: Path,
) -> None:
    root = _copy_collection(tmp_path)
    target = (
        root
        / "knowledge"
        / "seed_documents"
        / "en"
        / "01_financial_foundations.md"
    )

    text = target.read_text(encoding="utf-8")
    text = text.replace(
        'review_status: "approved_seed"',
        'review_status: "draft_requires_source_review"',
    )
    text = text.replace(
        'reviewed_at: "2026-07-26"',
        "reviewed_at: null",
    )
    target.write_text(
        text,
        encoding="utf-8",
        newline="\n",
    )

    validator.update_hashes(root)

    issues = validator.validate_collection(
        root,
        require_approved=True,
    )

    assert any(
        issue.path == str(target)
        and issue.message == "document is not approved_seed"
        for issue in issues
    )

