"""Unit tests for the canonical evidence/request hashing functions.

Pure functions: no SQLAlchemy, no fakes, no I/O.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from stock_research_core.domain.live_research.hashing import (
    compute_evidence_content_hash,
    compute_request_hash,
    normalize_query,
)

PUBLISHED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _evidence_kwargs(**overrides: object) -> dict:
    defaults: dict = dict(
        source_type="SEC_OFFICIAL_FILING",
        classification="OFFICIAL",
        source_url="https://www.sec.gov/example",
        official_identifier="0001234567-26-000001",
        source_title="Form 10-K",
        publisher="SEC",
        published_at=PUBLISHED_AT,
        raw_excerpt="Revenue increased 10% year over year.",
        normalized_text="revenue increased 10% year over year",
        structured_facts={"revenue": 100, "currency": "USD"},
    )
    defaults.update(overrides)
    return defaults


def test_identical_payloads_produce_identical_hashes() -> None:
    first = compute_evidence_content_hash(**_evidence_kwargs())
    second = compute_evidence_content_hash(**_evidence_kwargs())
    assert first == second


def test_reordered_structured_facts_keys_do_not_change_hash() -> None:
    first = compute_evidence_content_hash(**_evidence_kwargs(structured_facts={"a": 1, "b": 2}))
    second = compute_evidence_content_hash(**_evidence_kwargs(structured_facts={"b": 2, "a": 1}))
    assert first == second


def test_crlf_and_lf_input_canonicalize_to_the_same_hash() -> None:
    crlf = compute_evidence_content_hash(**_evidence_kwargs(raw_excerpt="line one\r\nline two"))
    lf = compute_evidence_content_hash(**_evidence_kwargs(raw_excerpt="line one\nline two"))
    assert crlf == lf


def test_changing_a_persisted_field_changes_the_hash() -> None:
    baseline = compute_evidence_content_hash(**_evidence_kwargs())
    changed = compute_evidence_content_hash(**_evidence_kwargs(source_title="A different title"))
    assert baseline != changed


def test_evidence_id_run_id_and_retrieved_at_are_not_hash_inputs() -> None:
    # These fields are not accepted as parameters at all - this test
    # documents that omission is intentional: the same kwargs always
    # produce the same hash regardless of what evidence_id/run_id/
    # retrieved_at happen to be on the eventual EvidenceItem instance.
    first = compute_evidence_content_hash(**_evidence_kwargs())
    second = compute_evidence_content_hash(**_evidence_kwargs())
    assert first == second
    assert "evidence_id" not in compute_evidence_content_hash.__code__.co_varnames
    assert "run_id" not in compute_evidence_content_hash.__code__.co_varnames
    assert "retrieved_at" not in compute_evidence_content_hash.__code__.co_varnames


def test_hash_output_is_64_lowercase_hex_characters() -> None:
    result = compute_evidence_content_hash(**_evidence_kwargs())
    assert len(result) == 64
    assert all(ch in "0123456789abcdef" for ch in result)


def test_both_source_fields_present_still_hashes_deterministically() -> None:
    first = compute_evidence_content_hash(**_evidence_kwargs())
    second = compute_evidence_content_hash(
        **_evidence_kwargs(source_url="https://www.sec.gov/example", official_identifier="0001234567-26-000001")
    )
    assert first == second


def test_none_fields_serialize_to_a_stable_representation() -> None:
    first = compute_evidence_content_hash(
        **_evidence_kwargs(source_url=None, published_at=None, normalized_text=None, structured_facts=None)
    )
    second = compute_evidence_content_hash(
        **_evidence_kwargs(source_url=None, published_at=None, normalized_text=None, structured_facts=None)
    )
    assert first == second
    assert len(first) == 64


# ---------------------------------------------------------------------------
# normalize_query / compute_request_hash
# ---------------------------------------------------------------------------


def test_normalize_query_lowercases_and_collapses_whitespace() -> None:
    assert normalize_query("  What   is\tAAPL's   revenue?  ") == "what is aapl's revenue?"


def test_compute_request_hash_is_deterministic() -> None:
    security_id = uuid4()
    first = compute_request_hash(
        normalized_query="what is aapl's revenue?", scope="COMPANY_OVERVIEW",
        subject_security_id=security_id, subject_raw_text=None,
    )
    second = compute_request_hash(
        normalized_query="what is aapl's revenue?", scope="COMPANY_OVERVIEW",
        subject_security_id=security_id, subject_raw_text=None,
    )
    assert first == second
    assert len(first) == 64


def test_compute_request_hash_changes_with_different_query() -> None:
    security_id = uuid4()
    first = compute_request_hash(
        normalized_query="what is aapl's revenue?", scope="COMPANY_OVERVIEW",
        subject_security_id=security_id, subject_raw_text=None,
    )
    second = compute_request_hash(
        normalized_query="what is aapl's guidance?", scope="COMPANY_OVERVIEW",
        subject_security_id=security_id, subject_raw_text=None,
    )
    assert first != second
