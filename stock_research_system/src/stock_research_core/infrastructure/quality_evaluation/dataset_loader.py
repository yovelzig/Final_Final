"""Filesystem JSONL -> curated `QualityEvaluationCase` loading, used by
both the CLI (`--validate-suite`/`--import-suite`) and the admin suite-
import API. Delegates all parsing/validation to the pure
`application.quality_evaluation.datasets` module - this file only owns
the filesystem read and a bounded file-size guard.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from stock_research_core.application.quality_evaluation.datasets import (
    DatasetValidationError,
    build_cases,
    compute_dataset_hash,
    parse_jsonl,
)
from stock_research_core.domain.quality_evaluation.models import QualityEvaluationCase

#: Spec section 22: "Enforce size limits" on suite-import uploads.
MAX_DATASET_FILE_SIZE_BYTES = 5 * 1024 * 1024


def load_cases_from_file(path: Path, *, suite_id: UUID, case_version: str) -> tuple[list[QualityEvaluationCase], str]:
    """Returns `(cases, dataset_hash)`. Raises `DatasetValidationError`
    for anything malformed - never a partial import."""
    resolved = path.resolve()
    if not resolved.is_file():
        raise DatasetValidationError(f"'{path}' is not a file.")
    size = resolved.stat().st_size
    if size > MAX_DATASET_FILE_SIZE_BYTES:
        raise DatasetValidationError(
            f"'{path}' is {size} bytes, exceeding the {MAX_DATASET_FILE_SIZE_BYTES}-byte suite-import limit."
        )
    raw_text = resolved.read_text(encoding="utf-8")
    raw_lines = parse_jsonl(raw_text)
    dataset_hash = compute_dataset_hash(raw_lines)
    cases = build_cases(raw_lines, suite_id=suite_id, case_version=case_version)
    return cases, dataset_hash
