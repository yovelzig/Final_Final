"""Dataset loading/validation for curated evaluation-suite JSONL files
(spec sections 6, 10). Pure parsing/validation logic - the actual
filesystem read happens in `infrastructure.quality_evaluation.
dataset_loader`, which calls into this module with the raw text.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from stock_research_core.application.exceptions import StockResearchError
from stock_research_core.domain.quality_evaluation.models import QualityEvaluationCase

#: Keys a curated case JSONL line may carry - matches
#: `QualityEvaluationCase`'s own fields (minus `case_id`/`suite_id`/
#: `status`/`created_at`/`updated_at`, which the loader/service own).
_ALLOWED_CASE_KEYS = frozenset(
    {
        "external_case_id", "context_type", "user_input", "reference_answer", "reference_contexts",
        "reference_document_ids", "reference_chunk_ids", "expected_skill_ids", "expected_guardrail_category",
        "expected_refusal", "expected_fallback", "expected_intent", "expected_route", "expected_action_type",
        "expected_interrupt", "forbidden_phrases", "required_concepts", "metadata", "case_version",
    }
)


class DatasetValidationError(StockResearchError):
    """Raised for structural problems in a curated dataset file - never
    silently ignored, never partially imported."""


def compute_dataset_hash(raw_lines: list[dict[str, Any]]) -> str:
    """A stable SHA-256 over the dataset's content, independent of line
    order - two files with the same cases in a different order hash
    identically; any content change changes the hash."""
    canonical_records = sorted(
        (json.dumps(record, sort_keys=True, separators=(",", ":")) for record in raw_lines)
    )
    canonical = "\n".join(canonical_records)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_jsonl(raw_text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw_text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise DatasetValidationError(f"Line {line_number} is not valid JSON: {exc}") from exc
        if not isinstance(record, dict):
            raise DatasetValidationError(f"Line {line_number} must be a JSON object.")
        records.append(record)
    return records


def _validate_record_keys(record: dict[str, Any], *, line_number: int) -> None:
    disallowed = set(record.keys()) - _ALLOWED_CASE_KEYS
    if disallowed:
        raise DatasetValidationError(f"Line {line_number} has unrecognized fields: {sorted(disallowed)}")
    if "external_case_id" not in record:
        raise DatasetValidationError(f"Line {line_number} is missing required field 'external_case_id'.")


def build_cases(
    raw_lines: list[dict[str, Any]], *, suite_id: UUID, case_version: str,
) -> list[QualityEvaluationCase]:
    """Builds and validates every case in a parsed dataset. Raises
    `DatasetValidationError` (never partially returns) on: duplicate
    `external_case_id` within the same version, an unrecognized field,
    or any single case failing `QualityEvaluationCase`'s own validation
    (hash/no-secrets/uniqueness rules) - a curated dataset is imported
    as a whole or not at all."""
    seen_ids: set[str] = set()
    cases: list[QualityEvaluationCase] = []
    for line_number, record in enumerate(raw_lines, start=1):
        _validate_record_keys(record, line_number=line_number)
        external_id = record["external_case_id"]
        if external_id in seen_ids:
            raise DatasetValidationError(f"Duplicate external_case_id '{external_id}' at line {line_number}.")
        seen_ids.add(external_id)

        payload = dict(record)
        payload.setdefault("case_version", case_version)
        try:
            case = QualityEvaluationCase(case_id=uuid4(), suite_id=suite_id, **payload)
        except ValidationError as exc:
            raise DatasetValidationError(f"Case '{external_id}' (line {line_number}) failed validation: {exc}") from exc
        cases.append(case)
    # Deterministic ordering regardless of file order, so re-importing
    # the same content is a stable no-op comparison.
    cases.sort(key=lambda case: case.external_case_id)
    return cases
