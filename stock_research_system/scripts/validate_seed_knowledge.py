#!/usr/bin/env python3
"""Validate FinQuest's 15-document English seed knowledge collection.

The front matter uses a deliberately restricted, valid YAML subset:
top-level scalars and top-level lists. This validator uses only Python's
standard library, so Phase C1 does not add a production dependency.

Usage:
    python scripts/validate_seed_knowledge.py
    python scripts/validate_seed_knowledge.py --update-hashes
    python scripts/validate_seed_knowledge.py --require-approved
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED_FILES = [
    "01_financial_foundations.md",
    "02_budgeting_and_emergency_funds.md",
    "03_interest_and_compound_interest.md",
    "04_inflation_and_time_value_of_money.md",
    "05_stocks_bonds_and_etfs.md",
    "06_market_structure_and_order_types.md",
    "07_financial_statements.md",
    "08_financial_ratios.md",
    "09_fundamental_analysis.md",
    "10_portfolio_construction_and_diversification.md",
    "11_risk_volatility_and_drawdown.md",
    "12_behavioral_finance.md",
    "13_technical_analysis_foundations.md",
    "14_historical_market_crises.md",
    "15_investment_thesis_and_decision_journal.md",
]

REQUIRED_METADATA = {
    "document_id",
    "title",
    "slug",
    "version",
    "language",
    "difficulty",
    "content_type",
    "jurisdiction",
    "review_status",
    "collection",
    "concept_ids",
    "lesson_ids",
    "source_policy",
    "created_at",
    "reviewed_at",
    "requires_periodic_review",
}

REQUIRED_HEADINGS = [
    "## Learning Objectives",
    "## Prerequisite Knowledge",
    "## Core Concepts",
    "## Detailed Explanation",
    "## Worked Examples",
    "## Common Mistakes",
    "## Common Misconceptions",
    "## Practical Application",
    "## Knowledge Check",
    "## Knowledge Check Answers",
    "## Key Takeaways",
    "## Glossary",
    "## References and Further Reading",
]

ALLOWED_REVIEW_STATUSES = {
    "draft_requires_source_review",
    "approved_seed",
    "rejected",
}

PLACEHOLDERS = [
    "TODO",
    "TBD",
    "Lorem ipsum",
    "Example content here",
    "Add source later",
    "SOURCE_VERIFICATION_REQUIRED",
]

WORD_RE = re.compile(r"\b[\w’'-]+\b", re.UNICODE)
URL_RE = re.compile(r"https://[^\s)>]+")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str


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


def parse_restricted_yaml(text: str) -> dict[str, Any]:
    """Parse the controlled front-matter subset used by this collection."""
    result: dict[str, Any] = {}
    current_list_key: str | None = None

    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        if line.startswith("  - "):
            if current_list_key is None:
                raise ValueError(f"line {line_number}: list item without a list key")
            result[current_list_key].append(_parse_scalar(line[4:]))
            continue

        if line.startswith((" ", "\t")):
            raise ValueError(f"line {line_number}: unsupported nested YAML")

        if ":" not in line:
            raise ValueError(f"line {line_number}: expected key: value")

        key, raw = line.split(":", 1)
        key = key.strip()
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", key):
            raise ValueError(f"line {line_number}: invalid key {key!r}")

        raw = raw.strip()
        if not raw:
            result[key] = []
            current_list_key = key
        else:
            result[key] = _parse_scalar(raw)
            current_list_key = None

    return result


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise ValueError("file must begin with YAML front matter")
    closing = text.find("\n---\n", 4)
    if closing < 0:
        raise ValueError("closing YAML front-matter delimiter not found")
    metadata = parse_restricted_yaml(text[4:closing])
    return metadata, text[closing + 5 :]


def canonical_text_bytes(path: Path) -> bytes:
    """Return UTF-8 text with platform-independent LF line endings."""
    text = path.read_text(encoding="utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.encode("utf-8")


def sha256_file(path: Path) -> str:
    """Hash canonical text so Windows and Linux produce the same digest."""
    return hashlib.sha256(canonical_text_bytes(path)).hexdigest()


def body_word_count(body: str) -> int:
    return len(WORD_RE.findall(body))


def section_between(body: str, start: str, end: str | None) -> str:
    start_index = body.find(start)
    if start_index < 0:
        return ""
    start_index += len(start)
    if end is None:
        return body[start_index:]
    end_index = body.find(end, start_index)
    if end_index < 0:
        return body[start_index:]
    return body[start_index:end_index]


def numbered_item_count(section: str) -> int:
    return len(re.findall(r"(?m)^\d+\.\s+", section))


def validate_collection(
    root: Path,
    *,
    require_approved: bool = False,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seed_root = root / "knowledge" / "seed_documents"
    english_root = seed_root / "en"
    manifest_path = seed_root / "manifest.json"

    actual_files = sorted(path.name for path in english_root.glob("*.md"))
    if actual_files != REQUIRED_FILES:
        missing = sorted(set(REQUIRED_FILES) - set(actual_files))
        extra = sorted(set(actual_files) - set(REQUIRED_FILES))
        issues.append(
            ValidationIssue(
                str(english_root),
                f"required file mismatch; missing={missing}, extra={extra}",
            )
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append(
            ValidationIssue(str(manifest_path), f"invalid or unreadable JSON: {exc}")
        )
        return issues

    if manifest.get("collection") != "finquest_core_financial_education":
        issues.append(ValidationIssue(str(manifest_path), "unexpected collection"))
    if manifest.get("version") != 1:
        issues.append(ValidationIssue(str(manifest_path), "version must be 1"))
    if manifest.get("language") != "en":
        issues.append(ValidationIssue(str(manifest_path), "language must be en"))
    if manifest.get("document_count") != 15:
        issues.append(ValidationIssue(str(manifest_path), "document_count must be 15"))

    manifest_documents = manifest.get("documents")
    if not isinstance(manifest_documents, list) or len(manifest_documents) != 15:
        issues.append(
            ValidationIssue(
                str(manifest_path),
                "documents must contain exactly 15 entries",
            )
        )
        manifest_documents = []

    manifest_by_filename = {
        item.get("filename"): item
        for item in manifest_documents
        if isinstance(item, dict)
    }

    document_ids: set[str] = set()
    slugs: set[str] = set()

    for expected_index, filename in enumerate(REQUIRED_FILES, 1):
        path = english_root / filename
        manifest_filename = f"en/{filename}"

        if not path.exists():
            continue
        if path.stat().st_size == 0:
            issues.append(ValidationIssue(str(path), "file is empty"))
            continue

        text = path.read_text(encoding="utf-8")
        try:
            metadata, body = split_front_matter(text)
        except ValueError as exc:
            issues.append(ValidationIssue(str(path), str(exc)))
            continue

        missing_metadata = sorted(REQUIRED_METADATA - set(metadata))
        if missing_metadata:
            issues.append(
                ValidationIssue(str(path), f"missing metadata: {missing_metadata}")
            )

        expected_id = f"kb-en-{expected_index:03d}"
        document_id = metadata.get("document_id")
        if document_id != expected_id:
            issues.append(
                ValidationIssue(str(path), f"document_id must be {expected_id}")
            )
        if document_id in document_ids:
            issues.append(
                ValidationIssue(str(path), f"duplicate document_id {document_id!r}")
            )
        document_ids.add(document_id)

        slug = metadata.get("slug")
        if not isinstance(slug, str) or not re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*", slug
        ):
            issues.append(
                ValidationIssue(str(path), "slug must be lowercase kebab-case")
            )
        if slug in slugs:
            issues.append(ValidationIssue(str(path), f"duplicate slug {slug!r}"))
        slugs.add(slug)

        if metadata.get("language") != "en":
            issues.append(ValidationIssue(str(path), "language must be en"))
        if metadata.get("collection") != manifest.get("collection"):
            issues.append(
                ValidationIssue(str(path), "collection differs from manifest")
            )
        if metadata.get("content_type") != "educational_reference":
            issues.append(
                ValidationIssue(
                    str(path),
                    "content_type must be educational_reference",
                )
            )

        review_status = metadata.get("review_status")
        if review_status not in ALLOWED_REVIEW_STATUSES:
            issues.append(ValidationIssue(str(path), "invalid review_status"))
        if require_approved and review_status != "approved_seed":
            issues.append(
                ValidationIssue(str(path), "document is not approved_seed")
            )
        if review_status == "approved_seed" and not metadata.get("reviewed_at"):
            issues.append(
                ValidationIssue(str(path), "approved_seed requires reviewed_at")
            )

        concept_ids = metadata.get("concept_ids")
        if not isinstance(concept_ids, list) or not concept_ids:
            issues.append(
                ValidationIssue(str(path), "concept_ids must be a non-empty list")
            )
        elif any(
            not re.fullmatch(r"[a-z][a-z0-9_]*", str(value))
            for value in concept_ids
        ):
            issues.append(
                ValidationIssue(
                    str(path),
                    "concept_ids must be lowercase snake_case",
                )
            )

        difficulty = metadata.get("difficulty")
        if not isinstance(difficulty, list) or not difficulty:
            issues.append(
                ValidationIssue(str(path), "difficulty must be a non-empty list")
            )

        if not re.search(r"(?m)^# [^\n]+$", body):
            issues.append(ValidationIssue(str(path), "missing H1 title"))
        for heading in REQUIRED_HEADINGS:
            if heading not in body:
                issues.append(
                    ValidationIssue(str(path), f"missing heading: {heading}")
                )

        word_count = body_word_count(body)
        if not 1500 <= word_count <= 3000:
            issues.append(
                ValidationIssue(
                    str(path),
                    f"body word count {word_count} is outside 1500..3000",
                )
            )

        questions = section_between(
            body,
            "## Knowledge Check",
            "## Knowledge Check Answers",
        )
        answers = section_between(
            body,
            "## Knowledge Check Answers",
            "## Key Takeaways",
        )
        question_count = numbered_item_count(questions)
        answer_count = numbered_item_count(answers)

        if not 5 <= question_count <= 10:
            issues.append(
                ValidationIssue(
                    str(path),
                    f"knowledge-check question count must be 5..10, got {question_count}",
                )
            )
        if answer_count != question_count:
            issues.append(
                ValidationIssue(
                    str(path),
                    f"answer count {answer_count} differs from question count {question_count}",
                )
            )

        references = section_between(
            body,
            "## References and Further Reading",
            None,
        )
        if len(URL_RE.findall(references)) < 2:
            issues.append(
                ValidationIssue(
                    str(path),
                    "references section must contain at least two HTTPS URLs",
                )
            )

        for placeholder in PLACEHOLDERS:
            if placeholder.lower() not in text.lower():
                continue
            if (
                placeholder == "SOURCE_VERIFICATION_REQUIRED"
                and review_status != "approved_seed"
            ):
                continue
            issues.append(
                ValidationIssue(
                    str(path),
                    f"forbidden placeholder marker: {placeholder}",
                )
            )

        entry = manifest_by_filename.get(manifest_filename)
        if entry is None:
            issues.append(
                ValidationIssue(
                    str(manifest_path),
                    f"missing manifest entry for {manifest_filename}",
                )
            )
            continue

        actual_hash = sha256_file(path)
        manifest_hash = entry.get("content_hash")
        if not isinstance(manifest_hash, str) or not SHA_RE.fullmatch(
            manifest_hash
        ):
            issues.append(
                ValidationIssue(
                    str(manifest_path),
                    f"invalid hash for {manifest_filename}",
                )
            )
        elif manifest_hash != actual_hash:
            issues.append(
                ValidationIssue(
                    str(manifest_path),
                    f"hash mismatch for {manifest_filename}",
                )
            )

        for key in (
            "document_id",
            "title",
            "slug",
            "review_status",
            "difficulty",
            "concept_ids",
        ):
            if entry.get(key) != metadata.get(key):
                issues.append(
                    ValidationIssue(
                        str(manifest_path),
                        f"{key} mismatch for {manifest_filename}",
                    )
                )

    return issues


def update_hashes(root: Path) -> None:
    manifest_path = root / "knowledge" / "seed_documents" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    for entry in manifest["documents"]:
        path = root / "knowledge" / "seed_documents" / entry["filename"]
        metadata, _ = split_front_matter(path.read_text(encoding="utf-8"))
        entry["content_hash"] = sha256_file(path)
        entry["document_id"] = metadata["document_id"]
        entry["title"] = metadata["title"]
        entry["slug"] = metadata["slug"]
        entry["difficulty"] = metadata["difficulty"]
        entry["concept_ids"] = metadata["concept_ids"]
        entry["review_status"] = metadata["review_status"]

    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--update-hashes", action="store_true")
    parser.add_argument("--require-approved", action="store_true")
    args = parser.parse_args(argv)

    if args.update_hashes:
        update_hashes(args.root)

    issues = validate_collection(
        args.root,
        require_approved=args.require_approved,
    )

    if issues:
        print(
            f"Seed knowledge validation failed with {len(issues)} issue(s):",
            file=sys.stderr,
        )
        for issue in issues:
            print(f"- {issue.path}: {issue.message}", file=sys.stderr)
        return 1

    status = "approved" if args.require_approved else "draft-or-approved"
    print(
        "Seed knowledge validation passed: "
        f"15 documents, hashes valid, status={status}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
