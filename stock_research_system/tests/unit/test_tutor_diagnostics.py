"""Unit tests for `application.ai_tutor.diagnostics` (spec G2D2 section 2):
bounded, allow-listed structured logging - never a free-text field, never
raw prompts/answers/chunk content/credentials."""

from __future__ import annotations

import io
import json
import logging
from uuid import uuid4

import pytest

from stock_research_core.application.ai_tutor.diagnostics import TutorDiagnosticIssueCode, log_tutor_diagnostic
from stock_research_core.domain.ai_tutor.enums import GroundingStatus, TutorProviderType
from stock_research_core.infrastructure.operations.structured_logging import configure_structlog, get_logger


@pytest.fixture
def captured_logs():
    buffer = io.StringIO()
    original_handlers = logging.getLogger().handlers
    try:
        yield buffer
    finally:
        logging.getLogger().handlers = original_handlers


class TestIssueCodes:
    def test_exactly_the_ten_spec_codes_are_present(self) -> None:
        assert TutorDiagnosticIssueCode.ALL == {
            "RETRIEVAL_INSUFFICIENT", "MODEL_TIMEOUT", "PROVIDER_ERROR", "MALFORMED_MODEL_RESPONSE",
            "MISSING_CITATIONS", "INVALID_CITATION_CHUNK_ID", "UNVERIFIED_URL", "UNSAFE_GENERATED_OUTPUT",
            "OUTPUT_SCHEMA_VIOLATION", "REPAIR_ATTEMPT_FAILED",
        }


class TestLogTutorDiagnostic:
    def test_only_allow_listed_fields_are_logged(self, captured_logs: io.StringIO) -> None:
        configure_structlog(environment="production", service_name="finquest-test", stream=captured_logs)

        log_tutor_diagnostic(
            provider_type=TutorProviderType.OLLAMA_CLOUD,
            model_name="gpt-oss:20b",
            attempt_number=1,
            retrieval_candidate_count=5,
            cited_id_count=2,
            grounding_status=GroundingStatus.GROUNDED,
            issue_codes=[TutorDiagnosticIssueCode.MISSING_CITATIONS],
            conversation_id=uuid4(),
            coach_correlation_id=uuid4(),
            elapsed_ms=42.5,
        )

        parsed = json.loads(captured_logs.getvalue().strip())
        expected_keys = {
            "event", "level", "timestamp", "logger", "service", "environment",
            "provider_type", "model_name", "attempt_number", "retrieval_candidate_count", "cited_id_count",
            "grounding_status", "issue_codes", "conversation_id", "coach_correlation_id", "elapsed_ms",
        }
        assert set(parsed.keys()) == expected_keys
        assert parsed["event"] == "tutor_diagnostic"
        assert parsed["provider_type"] == "OLLAMA_CLOUD"
        assert parsed["grounding_status"] == "GROUNDED"
        assert parsed["issue_codes"] == ["MISSING_CITATIONS"]

    def test_unknown_issue_code_is_dropped_not_logged_verbatim(self, captured_logs: io.StringIO) -> None:
        configure_structlog(environment="production", service_name="finquest-test", stream=captured_logs)

        log_tutor_diagnostic(
            provider_type=TutorProviderType.OLLAMA_CLOUD, model_name="m", attempt_number=1,
            retrieval_candidate_count=0, cited_id_count=0,
            issue_codes=["some raw model answer text leaked here"],
        )

        parsed = json.loads(captured_logs.getvalue().strip())
        assert parsed["issue_codes"] == []

    def test_optional_fields_default_to_none_or_empty(self, captured_logs: io.StringIO) -> None:
        configure_structlog(environment="production", service_name="finquest-test", stream=captured_logs)

        log_tutor_diagnostic(
            provider_type=TutorProviderType.OPENAI_COMPATIBLE, model_name="m", attempt_number=1,
            retrieval_candidate_count=3, cited_id_count=1,
        )

        parsed = json.loads(captured_logs.getvalue().strip())
        assert parsed["grounding_status"] is None
        assert parsed["issue_codes"] == []
        assert parsed["conversation_id"] is None
        assert parsed["coach_correlation_id"] is None

    def test_rejects_unexpected_keyword_arguments(self) -> None:
        """The signature itself is the guardrail against a free-text
        field being added by accident - passing anything not in the
        allow-listed set is a `TypeError`, not a silently logged value."""
        with pytest.raises(TypeError):
            log_tutor_diagnostic(  # type: ignore[call-arg]
                provider_type=TutorProviderType.OLLAMA_CLOUD, model_name="m", attempt_number=1,
                retrieval_candidate_count=0, cited_id_count=0, raw_prompt="leaked prompt text",
            )
