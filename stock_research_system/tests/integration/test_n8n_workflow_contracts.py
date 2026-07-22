"""Validates every `n8n/workflows/*.json` file: valid JSON, valid n8n
workflow structure, no embedded credentials, no PostgreSQL node, a
bounded polling loop, terminal-state handling, and a job type that
actually exists in `BackgroundJobType`.

Lives under `tests/integration/` per the spec's placement, but is
deliberately *not* marked `@pytest.mark.integration`: it needs no
database, only local files, so it always runs rather than being skipped
whenever the test Postgres instance is unreachable.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from stock_research_core.domain.operations.enums import BackgroundJobType

_N8N_DIR = Path(__file__).resolve().parents[2] / "n8n"
_WORKFLOWS_DIR = _N8N_DIR / "workflows"

_TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "CANCELLED", "SKIPPED"}
_FORBIDDEN_NODE_SUBSTRINGS = ("postgres", "mysql", "mongodb", "redis")
_RAW_CREDENTIAL_PATTERNS = [
    re.compile(r"postgresql(\+asyncpg)?://[^/\s\"]+:[^/\s\"]+@"),
    re.compile(r"redis://[^/\s\"]*:[^/\s\"]*@"),
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS-shaped access key, just in case
]

_WORKFLOW_JOB_TYPES = {
    "tracked-market-refresh.json": "TRACKED_MARKET_REFRESH",
    "portfolio-valuation.json": "PORTFOLIO_BATCH_VALUATION",
    "knowledge-refresh.json": "CURRICULUM_KNOWLEDGE_REFRESH",
    "retrieval-evaluation.json": "RETRIEVAL_EVALUATION",
    "quality-evaluation.json": "RAGAS_QUALITY_EVALUATION",
}


def _all_workflow_files() -> list[Path]:
    return sorted(_WORKFLOWS_DIR.glob("*.json"))


@pytest.fixture(scope="module")
def workflow_files() -> list[Path]:
    files = _all_workflow_files()
    assert files, f"No workflow JSON files found in {_WORKFLOWS_DIR}"
    return files


class TestWorkflowStructure:
    def test_expected_files_exist(self) -> None:
        names = {p.name for p in _all_workflow_files()}
        assert names == {
            "tracked-market-refresh.json", "portfolio-valuation.json", "knowledge-refresh.json",
            "retrieval-evaluation.json", "system-readiness-watch.json", "quality-evaluation.json",
        }

    def test_every_file_is_valid_json(self, workflow_files: list[Path]) -> None:
        for path in workflow_files:
            json.loads(path.read_text(encoding="utf-8"))  # raises on invalid JSON

    def test_every_file_has_the_required_n8n_workflow_keys(self, workflow_files: list[Path]) -> None:
        for path in workflow_files:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in ("name", "nodes", "connections", "active", "id"):
                assert key in data, f"{path.name} is missing required key '{key}'"
            assert isinstance(data["nodes"], list) and data["nodes"]
            assert isinstance(data["connections"], dict)
            assert data["active"] is False, f"{path.name} must not import already-active"

    def test_every_node_has_required_fields(self, workflow_files: list[Path]) -> None:
        for path in workflow_files:
            data = json.loads(path.read_text(encoding="utf-8"))
            for node in data["nodes"]:
                for key in ("id", "name", "type", "position", "parameters"):
                    assert key in node, f"{path.name}: node missing '{key}': {node}"


class TestNoRealCredentials:
    def test_no_raw_credential_shaped_strings(self, workflow_files: list[Path]) -> None:
        for path in workflow_files:
            text = path.read_text(encoding="utf-8")
            for pattern in _RAW_CREDENTIAL_PATTERNS:
                assert not pattern.search(text), f"{path.name} appears to contain an embedded credential"

    def test_credentials_are_referenced_by_placeholder_not_populated(self, workflow_files: list[Path]) -> None:
        for path in workflow_files:
            data = json.loads(path.read_text(encoding="utf-8"))
            for node in data["nodes"]:
                credentials = node.get("credentials")
                if credentials:
                    for cred in credentials.values():
                        assert cred.get("id", "").startswith("__REPLACE"), (
                            f"{path.name}: node '{node['name']}' credential must be a placeholder"
                        )


class TestNoDatabaseAccess:
    def test_no_database_node_types(self, workflow_files: list[Path]) -> None:
        for path in workflow_files:
            data = json.loads(path.read_text(encoding="utf-8"))
            for node in data["nodes"]:
                node_type = node["type"].lower()
                for forbidden in _FORBIDDEN_NODE_SUBSTRINGS:
                    assert forbidden not in node_type, f"{path.name}: node '{node['name']}' touches {forbidden}"

    def test_http_requests_target_only_the_finquest_api(self, workflow_files: list[Path]) -> None:
        for path in workflow_files:
            data = json.loads(path.read_text(encoding="utf-8"))
            for node in data["nodes"]:
                if node["type"] == "n8n-nodes-base.httpRequest":
                    url = node["parameters"]["url"]
                    assert "/api/v1/integrations/n8n/" in url, f"{path.name}: {node['name']} does not call the n8n integration API"


class TestPollingAndTerminalStates:
    @pytest.mark.parametrize("filename", list(_WORKFLOW_JOB_TYPES.keys()))
    def test_job_trigger_workflows_have_a_bounded_poll_loop(self, filename: str) -> None:
        data = json.loads((_WORKFLOWS_DIR / filename).read_text(encoding="utf-8"))
        node_names = {node["name"] for node in data["nodes"]}
        assert "Wait Before Poll" in node_names
        assert "Poll Job Status" in node_names
        assert "Increment Attempt" in node_names
        assert "Is Terminal Or Timed Out?" in node_names

        init_node = next(n for n in data["nodes"] if n["name"] == "Init Polling State")
        assert "maxAttempts" in init_node["parameters"]["jsCode"]
        assert "waitSeconds" in init_node["parameters"]["jsCode"]

    @pytest.mark.parametrize("filename", list(_WORKFLOW_JOB_TYPES.keys()))
    def test_terminal_statuses_are_all_handled(self, filename: str) -> None:
        data = json.loads((_WORKFLOWS_DIR / filename).read_text(encoding="utf-8"))
        terminal_node = next(n for n in data["nodes"] if n["name"] == "Is Terminal Or Timed Out?")
        condition_text = json.dumps(terminal_node["parameters"])
        for status in _TERMINAL_STATUSES:
            assert status in condition_text, f"{filename}: terminal-state check does not reference {status}"

    @pytest.mark.parametrize("filename", list(_WORKFLOW_JOB_TYPES.keys()))
    def test_produces_a_structured_summary(self, filename: str) -> None:
        data = json.loads((_WORKFLOWS_DIR / filename).read_text(encoding="utf-8"))
        node_names = {node["name"] for node in data["nodes"]}
        assert "Build Structured Summary" in node_names

    @pytest.mark.parametrize("filename, expected_job_type", list(_WORKFLOW_JOB_TYPES.items()))
    def test_workflow_references_a_real_job_type(self, filename: str, expected_job_type: str) -> None:
        data = json.loads((_WORKFLOWS_DIR / filename).read_text(encoding="utf-8"))
        text = json.dumps(data)
        assert expected_job_type in text
        assert expected_job_type in {jt.value for jt in BackgroundJobType}

    @pytest.mark.parametrize("filename", list(_WORKFLOW_JOB_TYPES.keys()))
    def test_idempotency_key_is_generated(self, filename: str) -> None:
        data = json.loads((_WORKFLOWS_DIR / filename).read_text(encoding="utf-8"))
        build_request = next(n for n in data["nodes"] if n["name"] == "Build Request")
        assert "idempotencyKey" in build_request["parameters"]["jsCode"]
        assert "externalRequestId" in build_request["parameters"]["jsCode"]


class TestSystemReadinessWatch:
    def test_calls_the_integration_ready_endpoint(self) -> None:
        data = json.loads((_WORKFLOWS_DIR / "system-readiness-watch.json").read_text(encoding="utf-8"))
        urls = [n["parameters"]["url"] for n in data["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"]
        assert any("/api/v1/integrations/n8n/ready" in url for url in urls)

    def test_has_no_polling_loop_since_readiness_is_synchronous(self) -> None:
        data = json.loads((_WORKFLOWS_DIR / "system-readiness-watch.json").read_text(encoding="utf-8"))
        node_names = {node["name"] for node in data["nodes"]}
        assert "Wait Before Poll" not in node_names

    def test_notify_node_is_present_and_documented_as_a_placeholder(self) -> None:
        data = json.loads((_WORKFLOWS_DIR / "system-readiness-watch.json").read_text(encoding="utf-8"))
        notify = next(n for n in data["nodes"] if "Notify" in n["name"])
        assert notify["type"] == "n8n-nodes-base.noOp"


class TestOptionalLiveN8nImport:
    """Imports each workflow into a local n8n instance via its REST API,
    if one is reachable - never fails the suite when it is not (per spec:
    "do not require external n8n cloud access")."""

    def test_import_into_local_n8n_if_available(self, workflow_files: list[Path]) -> None:
        import httpx

        n8n_url = "http://localhost:5678"
        try:
            response = httpx.get(f"{n8n_url}/healthz", timeout=1.0)
            reachable = response.status_code == 200
        except httpx.HTTPError:
            reachable = False

        if not reachable:
            pytest.skip("No local n8n instance reachable at http://localhost:5678 - import check skipped, not failed.")

        for path in workflow_files:
            data = json.loads(path.read_text(encoding="utf-8"))
            response = httpx.post(f"{n8n_url}/rest/workflows", json=data, timeout=5.0)
            assert response.status_code < 500, f"n8n rejected {path.name}: {response.text}"
