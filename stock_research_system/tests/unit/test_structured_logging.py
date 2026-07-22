"""Unit tests for `infrastructure.operations.structured_logging`:
production JSON output, development console output, and recursive
redaction of sensitive log fields."""

from __future__ import annotations

import io
import json
import logging

import pytest

from stock_research_core.infrastructure.operations.structured_logging import configure_structlog, get_logger


@pytest.fixture
def captured_logs():
    buffer = io.StringIO()
    original_handlers = logging.getLogger().handlers
    try:
        yield buffer
    finally:
        logging.getLogger().handlers = original_handlers


class TestProductionJsonOutput:
    def test_emits_one_json_object_per_line(self, captured_logs: io.StringIO) -> None:
        configure_structlog(environment="production", service_name="finquest-test", stream=captured_logs)
        logger = get_logger("test.json")
        logger.info("job_started", job_id="abc123")

        lines = [line for line in captured_logs.getvalue().splitlines() if line.strip()]
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["event"] == "job_started"
        assert parsed["job_id"] == "abc123"
        assert parsed["service"] == "finquest-test"
        assert parsed["environment"] == "production"
        assert "timestamp" in parsed
        assert "level" in parsed

    def test_correlation_id_is_included_when_provided(self, captured_logs: io.StringIO) -> None:
        configure_structlog(environment="production", service_name="finquest-test", stream=captured_logs)
        logger = get_logger("test.correlation")
        logger.info("request_handled", correlation_id="corr-123", status_code=200)
        parsed = json.loads(captured_logs.getvalue().strip())
        assert parsed["correlation_id"] == "corr-123"

    def test_job_fields_are_included(self, captured_logs: io.StringIO) -> None:
        configure_structlog(environment="production", service_name="finquest-worker", stream=captured_logs)
        logger = get_logger("test.job")
        logger.info(
            "job_execution_finished", job_id="j1", job_type="PORTFOLIO_VALUATION", attempt_number=1,
            queue="finquest.portfolio", worker_name="celery-worker:1",
        )
        parsed = json.loads(captured_logs.getvalue().strip())
        assert parsed["job_id"] == "j1"
        assert parsed["job_type"] == "PORTFOLIO_VALUATION"
        assert parsed["attempt_number"] == 1
        assert parsed["queue"] == "finquest.portfolio"


class TestDevelopmentConsoleOutput:
    def test_is_not_raw_json(self, captured_logs: io.StringIO) -> None:
        configure_structlog(environment="development", service_name="finquest-test", json_output=False, stream=captured_logs)
        logger = get_logger("test.console")
        logger.info("job_started", job_id="abc123")
        output = captured_logs.getvalue()
        assert output.strip()
        with pytest.raises(json.JSONDecodeError):
            json.loads(output.splitlines()[0])


class TestRedactionInLogs:
    @pytest.mark.parametrize("key,value", [
        ("authorization", "Bearer abc.def.ghi"),
        ("password", "hunter2"),
        ("api_key", "sk-secret"),
        ("refresh_token", "opaque-token-value"),
        ("database_url", "postgresql://user:pass@host/db"),
    ])
    def test_sensitive_fields_are_redacted(self, captured_logs: io.StringIO, key: str, value: str) -> None:
        configure_structlog(environment="production", service_name="finquest-test", stream=captured_logs)
        logger = get_logger("test.redact")
        logger.info("event", **{key: value})
        output = captured_logs.getvalue()
        assert value not in output
        assert "REDACTED" in output

    def test_nested_sensitive_fields_are_redacted(self, captured_logs: io.StringIO) -> None:
        configure_structlog(environment="production", service_name="finquest-test", stream=captured_logs)
        logger = get_logger("test.redact_nested")
        logger.info("event", context={"nested": {"password": "hunter2"}, "ok": "fine"})
        parsed = json.loads(captured_logs.getvalue().strip())
        assert parsed["context"]["nested"]["password"] == "***REDACTED***"
        assert parsed["context"]["ok"] == "fine"

    def test_non_sensitive_fields_are_preserved(self, captured_logs: io.StringIO) -> None:
        configure_structlog(environment="production", service_name="finquest-test", stream=captured_logs)
        logger = get_logger("test.preserve")
        logger.info("event", job_id="abc123", status="SUCCEEDED")
        parsed = json.loads(captured_logs.getvalue().strip())
        assert parsed["job_id"] == "abc123"
        assert parsed["status"] == "SUCCEEDED"
