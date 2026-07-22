"""Unit tests for `application.quality_evaluation.datasets` - JSONL
parsing, hashing, and case-building validation."""

from __future__ import annotations

from uuid import uuid4

import pytest

from stock_research_core.application.quality_evaluation.datasets import (
    DatasetValidationError,
    build_cases,
    compute_dataset_hash,
    parse_jsonl,
)


def test_parse_jsonl_skips_blank_lines() -> None:
    text = '{"external_case_id": "a"}\n\n{"external_case_id": "b"}\n'
    records = parse_jsonl(text)
    assert len(records) == 2


def test_parse_jsonl_rejects_invalid_json() -> None:
    with pytest.raises(DatasetValidationError, match="not valid JSON"):
        parse_jsonl("{not json}")


def test_parse_jsonl_rejects_non_object_lines() -> None:
    with pytest.raises(DatasetValidationError, match="JSON object"):
        parse_jsonl('["a", "b"]')


def test_dataset_hash_is_order_independent() -> None:
    records_a = [{"external_case_id": "a"}, {"external_case_id": "b"}]
    records_b = [{"external_case_id": "b"}, {"external_case_id": "a"}]
    assert compute_dataset_hash(records_a) == compute_dataset_hash(records_b)


def test_dataset_hash_changes_with_content() -> None:
    h1 = compute_dataset_hash([{"external_case_id": "a", "user_input": "x"}])
    h2 = compute_dataset_hash([{"external_case_id": "a", "user_input": "y"}])
    assert h1 != h2


def test_dataset_hash_is_stable_sha256() -> None:
    h = compute_dataset_hash([{"external_case_id": "a"}])
    assert len(h) == 64
    int(h, 16)  # raises if not valid hex


class TestBuildCases:
    def _valid_record(self, **overrides) -> dict:
        record = {
            "external_case_id": "rag-inflation-1", "context_type": "GENERAL_RAG",
            "user_input": "What is inflation?", "required_concepts": ["inflation"],
        }
        record.update(overrides)
        return record

    def test_builds_valid_cases(self) -> None:
        suite_id = uuid4()
        cases = build_cases([self._valid_record()], suite_id=suite_id, case_version="v1")
        assert len(cases) == 1
        assert cases[0].suite_id == suite_id
        assert cases[0].case_version == "v1"
        assert cases[0].status.value == "DRAFT"

    def test_rejects_duplicate_external_case_id(self) -> None:
        records = [self._valid_record(), self._valid_record()]
        with pytest.raises(DatasetValidationError, match="Duplicate external_case_id"):
            build_cases(records, suite_id=uuid4(), case_version="v1")

    def test_rejects_unrecognized_field(self) -> None:
        record = self._valid_record(not_a_real_field="oops")
        with pytest.raises(DatasetValidationError, match="unrecognized fields"):
            build_cases([record], suite_id=uuid4(), case_version="v1")

    def test_rejects_missing_external_case_id(self) -> None:
        record = self._valid_record()
        del record["external_case_id"]
        with pytest.raises(DatasetValidationError, match="external_case_id"):
            build_cases([record], suite_id=uuid4(), case_version="v1")

    def test_rejects_invalid_reference_to_a_nonexistent_enum(self) -> None:
        record = self._valid_record(context_type="NOT_A_REAL_CONTEXT_TYPE")
        with pytest.raises(DatasetValidationError, match="failed validation"):
            build_cases([record], suite_id=uuid4(), case_version="v1")

    def test_output_is_deterministically_ordered_by_external_case_id(self) -> None:
        records = [
            self._valid_record(external_case_id="zeta"), self._valid_record(external_case_id="alpha"),
        ]
        cases = build_cases(records, suite_id=uuid4(), case_version="v1")
        assert [case.external_case_id for case in cases] == ["alpha", "zeta"]

    def test_generated_cases_stay_draft_by_default(self) -> None:
        # Loader never accepts a caller-supplied status - every case
        # starts DRAFT (spec section 10: "Every case begins as DRAFT").
        cases = build_cases([self._valid_record()], suite_id=uuid4(), case_version="v1")
        assert cases[0].status.value == "DRAFT"

    def test_case_version_defaults_to_suite_version_when_absent(self) -> None:
        cases = build_cases([self._valid_record()], suite_id=uuid4(), case_version="v2")
        assert cases[0].case_version == "v2"

    def test_no_secrets_or_learner_identifiers_survive_case_metadata_validation(self) -> None:
        record = self._valid_record(metadata={"api_key": "sk-should-not-be-here"})
        with pytest.raises(DatasetValidationError):
            build_cases([record], suite_id=uuid4(), case_version="v1")
