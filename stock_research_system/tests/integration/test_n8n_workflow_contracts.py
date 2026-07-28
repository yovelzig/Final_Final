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
import shutil
import subprocess
from pathlib import Path

import pytest

from stock_research_core.domain.operations.enums import BackgroundJobType

_NODE_BINARY = shutil.which("node")

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

#: Phase G2C's live-research-run.json has its own node-naming convention
#: (Webhook/Manual Trigger, Status Switch, four dedicated summary
#: builders, etc.) and is deliberately verified by the dedicated
#: `TestLiveResearchRunWorkflow` class below instead of being folded into
#: the generic `_WORKFLOW_JOB_TYPES` parametrization above.
_LIVE_RESEARCH_WORKFLOW_FILE = "live-research-run.json"
_LIVE_RESEARCH_JOB_TYPE = "LIVE_RESEARCH_RUN_EXECUTION"
_RETRY_STATUSES = {"PENDING", "QUEUED", "RUNNING", "RETRY_SCHEDULED"}


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
            _LIVE_RESEARCH_WORKFLOW_FILE,
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


class TestLiveResearchRunWorkflow:
    """Phase G2C - dedicated contract tests for `live-research-run.json`,
    which does not share `_WORKFLOW_JOB_TYPES`'s generic node-naming
    convention (see the module-level comment above)."""

    @pytest.fixture()
    def data(self) -> dict:
        return json.loads((_WORKFLOWS_DIR / _LIVE_RESEARCH_WORKFLOW_FILE).read_text(encoding="utf-8"))

    @staticmethod
    def _node(data: dict, name: str) -> dict:
        return next(n for n in data["nodes"] if n["name"] == name)

    @staticmethod
    def _node_names(data: dict) -> set[str]:
        return {n["name"] for n in data["nodes"]}

    def test_references_the_live_research_job_type(self, data: dict) -> None:
        text = json.dumps(data)
        assert _LIVE_RESEARCH_JOB_TYPE in text
        assert _LIVE_RESEARCH_JOB_TYPE in {jt.value for jt in BackgroundJobType}

    def test_has_a_production_webhook_and_a_dev_only_manual_trigger(self, data: dict) -> None:
        names = self._node_names(data)
        assert "Webhook Trigger" in names
        assert "Manual Trigger" in names
        webhook = self._node(data, "Webhook Trigger")
        assert webhook["type"] == "n8n-nodes-base.webhook"
        manual = self._node(data, "Manual Trigger")
        assert manual["type"] == "n8n-nodes-base.manualTrigger"
        assert "dev" in manual.get("notes", "").lower() or "test" in manual.get("notes", "").lower()

    # -- Correction V3, item 1: inbound webhook authentication -----------

    def test_webhook_authentication_is_not_none(self, data: dict) -> None:
        webhook = self._node(data, "Webhook Trigger")
        assert webhook["parameters"].get("authentication") not in (None, "none")

    def test_webhook_uses_header_auth(self, data: dict) -> None:
        webhook = self._node(data, "Webhook Trigger")
        assert webhook["parameters"].get("authentication") == "headerAuth"

    def test_webhook_has_a_dedicated_inbound_credential_placeholder(self, data: dict) -> None:
        webhook = self._node(data, "Webhook Trigger")
        cred = webhook["credentials"]["httpHeaderAuth"]
        assert cred["id"] == "__REPLACE_WITH_YOUR_INBOUND_WEBHOOK_CREDENTIAL_ID__"
        assert cred["name"] == "FinQuest Live Research Webhook Auth"

    def test_inbound_and_outbound_credential_ids_differ(self, data: dict) -> None:
        webhook = self._node(data, "Webhook Trigger")
        inbound_id = webhook["credentials"]["httpHeaderAuth"]["id"]
        trigger = self._node(data, "Trigger FinQuest Job")
        outbound_id = trigger["credentials"]["httpHeaderAuth"]["id"]
        assert inbound_id != outbound_id
        assert inbound_id.startswith("__REPLACE")
        assert outbound_id.startswith("__REPLACE")

    def test_no_credential_header_name_or_value_present_in_json(self, data: dict) -> None:
        # The actual header name/value pair for either credential lives
        # only in n8n's own encrypted credential store - never in this
        # exported JSON. The Webhook node's own parameters carry nothing
        # but the `authentication` mode switch - no inline "name"/"value"
        # header-auth configuration.
        webhook = self._node(data, "Webhook Trigger")
        params_text = json.dumps(webhook["parameters"])
        assert '"name"' not in params_text
        assert '"value"' not in params_text

    def test_production_path_requires_invocation_id_before_validation_passes(self, data: dict) -> None:
        validate = self._node(data, "Validate / Build Request")
        code = validate["parameters"]["jsCode"]
        assert "invocation_id" in code
        assert "validationError" in code
        # invocation_id is only auto-generated on the isolated dev/testing
        # (manual) path - never on the production Webhook path. Verified
        # by relative ordering: the "isManual" guard and the production
        # failure return both precede the manual-only temporary-UUID call.
        assert "isManual" in code
        assert "generateTemporaryUuidV4" in code
        is_manual_check_pos = code.index("if (!isManual)")
        production_failure_pos = code.index("invocation_id is required for a production request")
        temp_uuid_call_pos = code.index("invocationId = generateTemporaryUuidV4()")
        assert is_manual_check_pos < temp_uuid_call_pos
        assert production_failure_pos < temp_uuid_call_pos

    def test_manual_uuid_generation_is_isolated_to_the_dev_testing_path(self, data: dict) -> None:
        manual_node = self._node(data, "Manual Trigger")
        assert "dev" in manual_node.get("notes", "").lower() or "test" in manual_node.get("notes", "").lower()
        # No other node in the workflow generates a UUID - only the single
        # guarded call inside "Validate / Build Request".
        for node in data["nodes"]:
            if node["name"] == "Validate / Build Request":
                continue
            node_text = json.dumps(node.get("parameters", {}))
            assert "generateTemporaryUuidV4" not in node_text

    def test_no_require_crypto_remains_anywhere_in_the_file(self, data: dict) -> None:
        """Correction V2: n8n Cloud code nodes run in a restricted sandbox
        and must never depend on Node's built-in `crypto` module - the
        dev-only temporary UUID is generated with pure JavaScript instead."""
        text = json.dumps(data)
        assert "require(" not in text
        assert "crypto.randomUUID" not in text

    def test_malformed_invocation_id_cannot_reach_the_job_trigger_node(self, data: dict) -> None:
        validate = self._node(data, "Validate / Build Request")
        code = validate["parameters"]["jsCode"]
        # Type check, trim, canonical-UUID regex, and casing normalization
        # all run - and can all return a validationError - before scope
        # parsing even begins, which itself gates "Trigger FinQuest Job"
        # via the pre-existing "Validation Passed?" node (see
        # test_validation_failure_never_reaches_the_job_trigger_node).
        assert "invocationId.trim()" in code
        assert "invocationId.toLowerCase()" in code
        assert "invocation_id must be a canonical UUID" in code
        assert "invocation_id must be a string" in code
        uuid_pattern_pos = code.index("UUID_PATTERN")
        scope_parsing_pos = code.index("const scope = body.scope")
        assert uuid_pattern_pos < scope_parsing_pos

    def test_validation_failure_never_reaches_the_job_trigger_node(self, data: dict) -> None:
        gate_targets = {
            edge["node"]
            for branch in data["connections"]["Validation Passed?"]["main"]
            for edge in branch
        }
        # Correction V3: the false branch now routes through the
        # manual/production split ("Is Manual (Invalid Request)?") rather
        # than straight to "Validation Error Output".
        assert gate_targets == {"Trigger FinQuest Job", "Is Manual (Invalid Request)?"}
        downstream_of_invalid = {
            edge["node"]
            for branch in data["connections"]["Is Manual (Invalid Request)?"]["main"]
            for edge in branch
        }
        assert downstream_of_invalid == {"Validation Error Output", "Build Validation Error Response"}
        assert "Trigger FinQuest Job" not in downstream_of_invalid
        # Validation Error Output has no outgoing edge at all - in
        # particular, never one to Trigger FinQuest Job.
        assert "Validation Error Output" not in data["connections"]

    def test_exactly_one_finquest_job_trigger_request(self, data: dict) -> None:
        trigger_nodes = [
            n for n in data["nodes"]
            if n["type"] == "n8n-nodes-base.httpRequest" and n["parameters"]["method"] == "POST"
            and n["parameters"]["url"].rstrip("/").endswith("/api/v1/integrations/n8n/jobs")
        ]
        assert len(trigger_nodes) == 1

    def test_required_headers_are_present_on_the_trigger_node(self, data: dict) -> None:
        trigger = self._node(data, "Trigger FinQuest Job")
        header_names = {h["name"] for h in trigger["parameters"]["headerParameters"]["parameters"]}
        assert header_names == {"X-FinQuest-Key-Id", "X-FinQuest-Request-ID", "Idempotency-Key", "Content-Type"}
        # X-FinQuest-Integration-Key is never a literal header - it comes
        # only from the httpHeaderAuth credential (validated below).
        assert "X-FinQuest-Integration-Key" not in json.dumps(trigger)

    def test_request_id_and_idempotency_key_are_separate_invocation_scoped_namespaces(self, data: dict) -> None:
        validate = self._node(data, "Validate / Build Request")
        code = validate["parameters"]["jsCode"]
        assert "livequery-req:" in code
        assert "livequery-idem:" in code
        assert "${invocationId}" in code

    def test_integration_secret_uses_credential_placeholder_everywhere(self, data: dict) -> None:
        # Correction V3: the Webhook Trigger's INBOUND credential is a
        # distinct placeholder from the OUTBOUND credential used by every
        # HTTP Request node - see test_inbound_and_outbound_credential_ids_differ.
        for node in data["nodes"]:
            credentials = node.get("credentials")
            if not credentials:
                continue
            for cred in credentials.values():
                if node["name"] == "Webhook Trigger":
                    assert cred["id"] == "__REPLACE_WITH_YOUR_INBOUND_WEBHOOK_CREDENTIAL_ID__"
                else:
                    assert cred["id"] == "__REPLACE_WITH_YOUR_CREDENTIAL_ID__"

    def test_no_raw_credential_literal_anywhere_in_file(self, data: dict) -> None:
        text = json.dumps(data)
        for forbidden in (
            "sk-", "Bearer ", "postgresql://", "postgres://", "redis://",
            "AKIA", "-----BEGIN",
        ):
            assert forbidden not in text

    def test_no_database_or_provider_nodes(self, data: dict) -> None:
        node_types = " ".join(n["type"].lower() for n in data["nodes"])
        for forbidden in ("postgres", "mysql", "mongodb", "redis"):
            assert forbidden not in node_types
        # Every httpRequest node's URL and every credential name/id must
        # never reference Perplexity or SEC EDGAR directly - free-text
        # documentation (e.g. "never calls Perplexity or SEC directly" in
        # `meta.description`) is expected and is not checked here.
        for node in data["nodes"]:
            if node["type"] != "n8n-nodes-base.httpRequest":
                continue
            url = node["parameters"]["url"].lower()
            for forbidden_provider in ("perplexity", "sec.gov", "sec-edgar", "secedgar", "edgar"):
                assert forbidden_provider not in url
        for node in data["nodes"]:
            for cred in node.get("credentials", {}).values():
                cred_text = json.dumps(cred).lower()
                for forbidden_provider in ("perplexity", "sec.gov", "sec-edgar", "secedgar", "edgar"):
                    assert forbidden_provider not in cred_text

    def test_first_poll_does_not_access_an_unexecuted_node(self, data: dict) -> None:
        """Correction V2: on the initial poll, 'Increment Poll Attempt' has
        not executed yet. 'Merge Polling State' must check `isExecuted`
        before ever calling `.first()` on that node reference, and must
        never call `.first(false)` (which throws in n8n rather than
        returning a safe sentinel when the referenced node has not run)."""
        merge_node = self._node(data, "Merge Polling State")
        code = merge_node["parameters"]["jsCode"]
        assert "isExecuted" in code
        assert "first(false)" not in code
        is_executed_pos = code.index("isExecuted")
        first_call_pos = code.index(".first().json.attempt")
        assert is_executed_pos < first_call_pos
        # On the initial poll (isExecuted === false), the fallback value
        # must be Init Polling State's own attempt (0) - never a bare
        # literal or an un-derived default.
        assert "state.attempt" in code

    def test_webhook_has_a_valid_response_mode(self, data: dict) -> None:
        """Correction V3: the workflow can poll for ~40 minutes, so the
        Webhook must not hold the connection open with `responseMode=
        lastNode` - it must use `responseMode=responseNode` paired with
        correctly wired `Respond to Webhook` nodes (see
        test_two_respond_to_webhook_nodes_exist_for_202_and_400)."""
        webhook = self._node(data, "Webhook Trigger")
        assert webhook["parameters"].get("responseMode") == "responseNode"
        node_types = {n["type"] for n in data["nodes"]}
        assert "n8n-nodes-base.respondToWebhook" in node_types

    def test_three_respond_to_webhook_nodes_exist_for_202_400_and_502(self, data: dict) -> None:
        """Final correction: a third Respond to Webhook node (502) covers a
        post-POST infrastructure/transport failure from FinQuest, alongside
        the pre-existing 202 (accepted) and 400 (pre-POST validation
        failure, now also reused for a post-POST 4xx rejection)."""
        respond_nodes = [n for n in data["nodes"] if n["type"] == "n8n-nodes-base.respondToWebhook"]
        assert len(respond_nodes) == 3
        status_codes = {n["parameters"]["options"]["responseCode"] for n in respond_nodes}
        assert status_codes == {202, 400, 502}

    def test_202_response_body_is_bounded_to_the_documented_fields(self, data: dict) -> None:
        build_response = self._node(data, "Build Job Accepted Response")
        code = build_response["parameters"]["jsCode"]
        assert "accepted: true" in code
        assert "job_id" in code
        assert "invocation_id" in code
        assert "POLLING_STARTED" in code
        respond_202 = self._node(data, "Respond 202 - Accepted")
        assert respond_202["parameters"]["options"]["responseCode"] == 202

    def test_400_response_body_is_bounded_and_never_a_traceback(self, data: dict) -> None:
        build_error = self._node(data, "Build Validation Error Response")
        code = build_error["parameters"]["jsCode"]
        assert "accepted: false" in code
        assert "validation_error" in code
        for forbidden in ("Traceback", "stack", "Error(", "throw "):
            assert forbidden not in code

    # -- Correction V3, item 3: the four manual/production x valid/invalid paths --

    def test_manual_valid_path_bypasses_the_respond_to_webhook_node(self, data: dict) -> None:
        true_targets = {e["node"] for e in data["connections"]["Is Manual (Job Triggered)?"]["main"][0]}
        assert true_targets == {"Init Polling State"}

    def test_production_valid_path_responds_202_and_still_continues_polling(self, data: dict) -> None:
        false_targets = {e["node"] for e in data["connections"]["Is Manual (Job Triggered)?"]["main"][1]}
        assert false_targets == {"Build Job Accepted Response", "Init Polling State"}
        build_accepted_targets = {e["node"] for e in data["connections"]["Build Job Accepted Response"]["main"][0]}
        assert build_accepted_targets == {"Respond 202 - Accepted"}
        # Polling continues unchanged regardless of which branch fed it.
        assert data["connections"]["Init Polling State"]["main"][0][0]["node"] == "Wait Before Poll"

    def test_manual_invalid_path_bypasses_respond_and_never_calls_finquest(self, data: dict) -> None:
        true_targets = {e["node"] for e in data["connections"]["Is Manual (Invalid Request)?"]["main"][0]}
        assert true_targets == {"Validation Error Output"}
        assert "Validation Error Output" not in data["connections"]

    def test_production_invalid_path_responds_400_before_any_finquest_call(self, data: dict) -> None:
        false_targets = {e["node"] for e in data["connections"]["Is Manual (Invalid Request)?"]["main"][1]}
        assert false_targets == {"Build Validation Error Response"}
        build_err_targets = {e["node"] for e in data["connections"]["Build Validation Error Response"]["main"][0]}
        assert build_err_targets == {"Respond 400 - Validation Error"}
        # Respond 400 has no outgoing edge - it is a terminal node, and in
        # particular never leads to Trigger FinQuest Job.
        assert "Respond 400 - Validation Error" not in data["connections"]

    # -- Correction V3, item 4: cloud-reachable FinQuest configuration ----

    def test_no_docker_internal_fallback_hostname_remains(self, data: dict) -> None:
        text = json.dumps(data)
        assert "finquest-api:8080" not in text
        assert "http://finquest-api" not in text

    def test_all_finquest_http_requests_use_the_configured_base_url(self, data: dict) -> None:
        """Final correction: every FinQuest HTTP Request node uses
        $json.apiBaseUrl/$json.keyId - the single validated/normalized
        value carried in the workflow state - rather than reading
        $vars.FINQUEST_API_BASE_URL directly."""
        for node in data["nodes"]:
            if node["type"] != "n8n-nodes-base.httpRequest":
                continue
            url = node["parameters"]["url"]
            assert url.startswith("={{ $json.apiBaseUrl }}"), (
                f"{node['name']} does not use the validated, workflow-state base URL"
            )
            header_names = {h["name"]: h["value"] for h in node["parameters"].get("headerParameters", {}).get("parameters", [])}
            if "X-FinQuest-Key-Id" in header_names:
                assert header_names["X-FinQuest-Key-Id"] == "={{ $json.keyId }}", (
                    f"{node['name']} does not use the validated, workflow-state key id"
                )

    def test_no_http_request_node_reads_the_raw_vars_finquest_config(self, data: dict) -> None:
        """Final correction: 'Validate / Build Request' is the ONLY node
        allowed to read $vars.FINQUEST_API_BASE_URL / $vars.FINQUEST_KEY_ID
        - every HTTP Request node must use the validated $json.apiBaseUrl /
        $json.keyId instead."""
        for node in data["nodes"]:
            if node["type"] != "n8n-nodes-base.httpRequest":
                continue
            node_text = json.dumps(node["parameters"])
            assert "$vars.FINQUEST_API_BASE_URL" not in node_text, f"{node['name']} reads $vars directly"
            assert "$vars.FINQUEST_KEY_ID" not in node_text, f"{node['name']} reads $vars directly"

    def test_only_validate_build_request_reads_the_raw_vars_finquest_config(self, data: dict) -> None:
        for node in data["nodes"]:
            if node["name"] == "Validate / Build Request":
                continue
            node_text = json.dumps(node.get("parameters", {}))
            assert "$vars.FINQUEST_API_BASE_URL" not in node_text, f"{node['name']} reads $vars directly"
            assert "$vars.FINQUEST_KEY_ID" not in node_text, f"{node['name']} reads $vars directly"

    def test_init_and_merge_polling_state_preserve_api_base_url_and_key_id(self, data: dict) -> None:
        init_code = self._node(data, "Init Polling State")["parameters"]["jsCode"]
        assert "apiBaseUrl" in init_code
        assert "keyId" in init_code
        merge_code = self._node(data, "Merge Polling State")["parameters"]["jsCode"]
        assert "apiBaseUrl" in merge_code
        assert "keyId" in merge_code

    def test_config_validation_precedes_the_job_trigger_node(self, data: dict) -> None:
        validate = self._node(data, "Validate / Build Request")
        code = validate["parameters"]["jsCode"]
        assert "FINQUEST_API_BASE_URL" in code
        assert "FINQUEST_KEY_ID" in code
        config_check_pos = code.index("configBaseUrl")
        scope_parsing_pos = code.index("const scope = body.scope")
        assert config_check_pos < scope_parsing_pos

    # -- Final correction, item 4: FinQuest 4xx/5xx never crashes the run --

    def test_trigger_finquest_job_never_crashes_on_a_non_2xx_response(self, data: dict) -> None:
        trigger = self._node(data, "Trigger FinQuest Job")
        response_opts = trigger["parameters"]["options"]["response"]["response"]
        assert response_opts["neverError"] is True
        assert response_opts["fullResponse"] is True
        assert trigger.get("onError") == "continueRegularOutput"

    def test_trigger_finquest_job_feeds_classify_trigger_response(self, data: dict) -> None:
        targets = {e["node"] for branch in data["connections"]["Trigger FinQuest Job"]["main"] for e in branch}
        assert targets == {"Classify Trigger Response"}

    def test_trigger_outcome_switch_routes_accepted_rejected_and_infra_failure(self, data: dict) -> None:
        classify_targets = {e["node"] for branch in data["connections"]["Classify Trigger Response"]["main"] for e in branch}
        assert classify_targets == {"Trigger Outcome Switch"}
        switch_node = self._node(data, "Trigger Outcome Switch")
        output_keys = [rule["outputKey"] for rule in switch_node["parameters"]["rules"]["values"]]
        assert output_keys == ["Accepted", "Rejected", "InfraFailure"]
        branches = data["connections"]["Trigger Outcome Switch"]["main"]
        assert branches[0][0]["node"] == "Is Manual (Job Triggered)?"
        assert branches[1][0]["node"] == "Is Manual (Rejected Request)?"
        assert branches[2][0]["node"] == "Is Manual (Infra Failure)?"
        # The 'extra' fallback output (an outcome value other than the three
        # defined rules, impossible by construction) is never silently
        # dropped - it is defensively routed to the same InfraFailure gate.
        assert switch_node["parameters"]["fallbackOutput"] == "extra"
        assert len(branches) == 4
        assert branches[3][0]["node"] == "Is Manual (Infra Failure)?"

    @staticmethod
    def _reachable(connections: dict, start: str) -> set[str]:
        seen: set[str] = set()
        queue = [start]
        while queue:
            current = queue.pop()
            for branch in connections.get(current, {}).get("main", []):
                for edge in branch:
                    if edge["node"] not in seen:
                        seen.add(edge["node"])
                        queue.append(edge["node"])
        return seen

    def test_rejected_request_never_reaches_polling(self, data: dict) -> None:
        reachable = self._reachable(data["connections"], "Is Manual (Rejected Request)?")
        assert "Init Polling State" not in reachable
        assert "Wait Before Poll" not in reachable
        assert "Trigger FinQuest Job" not in reachable
        assert "Respond 400 - Validation Error" in reachable
        assert "Validation Error Output" in reachable

    def test_infra_failure_never_reaches_polling(self, data: dict) -> None:
        reachable = self._reachable(data["connections"], "Is Manual (Infra Failure)?")
        assert "Init Polling State" not in reachable
        assert "Wait Before Poll" not in reachable
        assert "Trigger FinQuest Job" not in reachable
        assert "Respond 502 - Infra Failure" in reachable
        assert "Failure Output" in reachable

    def test_rejected_and_infra_failure_responses_are_bounded_and_never_a_traceback(self, data: dict) -> None:
        for node_name in ("Build Job Rejected Response", "Build Infra Failure Response", "Build Manual Rejected Output", "Build Manual Infra Failure Output"):
            code = self._node(data, node_name)["parameters"]["jsCode"]
            for forbidden in ("Traceback", "stack", "Error(", "throw ", "responseBody", "detail"):
                assert forbidden not in code, f"{node_name} leaks unbounded detail: {forbidden}"

    def test_polling_interval_is_15_seconds(self, data: dict) -> None:
        init_node = self._node(data, "Init Polling State")
        assert "waitSeconds = 15" in init_node["parameters"]["jsCode"]
        wait_node = self._node(data, "Wait Before Poll")
        assert wait_node["parameters"]["amount"] == "={{ $json.waitSeconds }}"
        assert wait_node["parameters"]["unit"] == "seconds"

    def test_deadline_is_approximately_40_minutes(self, data: dict) -> None:
        init_node = self._node(data, "Init Polling State")
        assert "40 * 60 * 1000" in init_node["parameters"]["jsCode"]

    def test_terminal_and_retry_statuses_are_both_referenced(self, data: dict) -> None:
        gate = self._node(data, "Is Terminal Or Timed Out?")
        condition_text = json.dumps(gate["parameters"])
        for status in _TERMINAL_STATUSES:
            assert status in condition_text
        merge_node = self._node(data, "Merge Polling State")
        # Retry-eligible statuses aren't named explicitly in the gate (it
        # loops on "not terminal and not timed out"), but they must be
        # valid BackgroundJobStatus values that are never listed as terminal.
        for status in _RETRY_STATUSES:
            assert status not in _TERMINAL_STATUSES

    def test_max_attempts_routes_to_timeout_not_operational_failure(self, data: dict) -> None:
        """Correction V2: the Status Switch's Timeout branch must fire on
        EITHER `timedOut === true` OR `attempt >= maxAttempts` - the
        bounded attempt-counter guard must never fall through to the
        fallback (Build Failure Summary / OPERATIONAL_FAILURE) output."""
        switch_node = self._node(data, "Status Switch")
        rules = switch_node["parameters"]["rules"]["values"]
        timeout_rule = next(rule for rule in rules if rule["outputKey"] == "Timeout")
        condition_text = json.dumps(timeout_rule["conditions"])
        assert timeout_rule["conditions"]["combinator"] == "or"
        assert "timedOut" in condition_text
        assert "attempt" in condition_text and "maxAttempts" in condition_text
        leftValues = {c["leftValue"] for c in timeout_rule["conditions"]["conditions"]}
        assert any("timedOut" in lv for lv in leftValues)
        assert any("attempt" in lv and "maxAttempts" in lv for lv in leftValues)

    def test_completed_with_evidence_branch_calls_the_evidence_endpoint(self, data: dict) -> None:
        get_evidence = self._node(data, "Get Evidence")
        assert get_evidence["type"] == "n8n-nodes-base.httpRequest"
        assert "/live-research/evidence" in get_evidence["parameters"]["url"]
        switch_targets = [branch[0]["node"] for branch in data["connections"]["Status Switch"]["main"]]
        assert switch_targets[0] == "Get Evidence"

    def test_no_evidence_branch_does_not_call_the_evidence_endpoint(self, data: dict) -> None:
        no_evidence_incoming = {
            src for src, conn in data["connections"].items()
            for branch in conn["main"]
            for edge in branch
            if edge["node"] == "Build No-Evidence Summary"
        }
        assert no_evidence_incoming == {"Status Switch"}

    def test_failure_branch_does_not_call_the_evidence_endpoint(self, data: dict) -> None:
        failure_incoming = {
            src for src, conn in data["connections"].items()
            for branch in conn["main"]
            for edge in branch
            if edge["node"] == "Build Failure Summary"
        }
        assert failure_incoming == {"Status Switch"}

    def test_timeout_branch_does_not_call_the_evidence_endpoint_and_preserves_ids(self, data: dict) -> None:
        timeout_incoming = {
            src for src, conn in data["connections"].items()
            for branch in conn["main"]
            for edge in branch
            if edge["node"] == "Build Timeout Summary"
        }
        assert timeout_incoming == {"Status Switch"}
        timeout_summary = self._node(data, "Build Timeout Summary")
        assert "jobId" in timeout_summary["parameters"]["jsCode"]
        assert "invocationId" in timeout_summary["parameters"]["jsCode"]

    def test_does_not_create_a_second_job_on_timeout(self, data: dict) -> None:
        # The only path into "Trigger FinQuest Job" is the initial
        # validation gate - "Build Timeout Summary" has no edge back to it.
        trigger_incoming = {
            src for src, conn in data["connections"].items()
            for branch in conn["main"]
            for edge in branch
            if edge["node"] == "Trigger FinQuest Job"
        }
        assert trigger_incoming == {"Validation Passed?"}


_VALID_ENV = {"FINQUEST_API_BASE_URL": "https://finquest.example.com", "FINQUEST_KEY_ID": "key-123"}
_FIXED_UUID = "11111111-1111-4111-8111-111111111111"

#: Each scenario: (is_manual, body, env_vars). Keyed by test name so a
#: single Node.js subprocess can evaluate every scenario in one process
#: (spawning a fresh Node process per scenario is needlessly slow) while
#: each still gets a fully independent $input/$execution/$vars shim.
_VALIDATE_SCENARIOS: dict[str, tuple[bool, dict, dict]] = {
    "whitespace_only_subject_raw_text": (
        True,
        {
            "invocation_id": _FIXED_UUID, "scope": "NEWS_SCAN",
            "original_question": "What happened?", "subject_raw_text": "   ",
        },
        _VALID_ENV,
    ),
    "non_string_original_question": (
        True,
        {"invocation_id": _FIXED_UUID, "scope": "GENERAL_QUESTION", "original_question": 12345},
        _VALID_ENV,
    ),
    "whitespace_only_original_question": (
        True,
        {"invocation_id": _FIXED_UUID, "scope": "GENERAL_QUESTION", "original_question": "   "},
        _VALID_ENV,
    ),
    "valid_normalized_input": (
        True,
        {
            "invocation_id": _FIXED_UUID, "scope": "NEWS_SCAN",
            "original_question": "  What recent developments affect NVIDIA?  ",
            "subject_raw_text": "  NVIDIA Corporation  ",
        },
        _VALID_ENV,
    ),
    "missing_finquest_api_base_url": (
        True,
        {"invocation_id": _FIXED_UUID, "scope": "GENERAL_QUESTION", "original_question": "What is going on?"},
        {"FINQUEST_KEY_ID": "key-123"},
    ),
    "missing_finquest_key_id": (
        True,
        {"invocation_id": _FIXED_UUID, "scope": "GENERAL_QUESTION", "original_question": "What is going on?"},
        {"FINQUEST_API_BASE_URL": "https://finquest.example.com"},
    ),
    "production_non_https_base_url": (
        False,
        {"invocation_id": _FIXED_UUID, "scope": "GENERAL_QUESTION", "original_question": "What is going on?"},
        {"FINQUEST_API_BASE_URL": "http://insecure.example.com", "FINQUEST_KEY_ID": "key-123"},
    ),
    "manual_non_https_base_url": (
        True,
        {"invocation_id": _FIXED_UUID, "scope": "GENERAL_QUESTION", "original_question": "What is going on?"},
        {"FINQUEST_API_BASE_URL": "http://localhost:8080", "FINQUEST_KEY_ID": "key-123"},
    ),
    # -- Final correction, item 1: safe input envelope ---------------------
    # Wrapped exactly as n8n's own Webhook Trigger node represents an
    # incoming request: {headers, params, query, body: <caller's payload>}.
    "null_body": (False, {"body": None}, _VALID_ENV),
    "array_body": (False, {"body": [1, 2, 3]}, _VALID_ENV),
    "string_body": (False, {"body": "just a plain string"}, _VALID_ENV),
    "number_body": (False, {"body": 42}, _VALID_ENV),
    # -- Final correction, item 2: FINQUEST_API_BASE_URL/KEY_ID parsing ---
    "malformed_api_base_url": (
        True,
        {"invocation_id": _FIXED_UUID, "scope": "GENERAL_QUESTION", "original_question": "What is going on?"},
        {"FINQUEST_API_BASE_URL": "not a url at all", "FINQUEST_KEY_ID": "key-123"},
    ),
    "api_base_url_without_a_hostname": (
        True,
        {"invocation_id": _FIXED_UUID, "scope": "GENERAL_QUESTION", "original_question": "What is going on?"},
        {"FINQUEST_API_BASE_URL": "file:///no/host/here", "FINQUEST_KEY_ID": "key-123"},
    ),
    "api_base_url_with_embedded_credentials": (
        True,
        {"invocation_id": _FIXED_UUID, "scope": "GENERAL_QUESTION", "original_question": "What is going on?"},
        {"FINQUEST_API_BASE_URL": "https://svc-user:svc-pass@finquest.example.com", "FINQUEST_KEY_ID": "key-123"},
    ),
    "whitespace_surrounded_url_and_key_id_are_normalized": (
        True,
        {"invocation_id": _FIXED_UUID, "scope": "GENERAL_QUESTION", "original_question": "What is going on?"},
        {"FINQUEST_API_BASE_URL": "   https://finquest.example.com/   ", "FINQUEST_KEY_ID": "   key-123   "},
    ),
}


def _run_validate_build_request_scenarios(js_code: str, scenarios: dict[str, tuple[bool, dict, dict]]) -> dict[str, dict]:
    """Executes the 'Validate / Build Request' n8n Code node's `jsCode` in
    a single, real Node.js subprocess against every named scenario, each
    with its own minimal `$input`/`$execution`/`$vars` shim. This node
    never references any other named node via `$()`, so the shim is exact
    enough to genuinely prove its validation and normalization behavior
    end to end (Correction V3, item 5), rather than only pattern-matching
    the source text. Batched into one subprocess (rather than one per
    scenario) purely for speed."""
    scenario_list = [
        {"name": name, "isManual": is_manual, "body": body, "envVars": env_vars}
        for name, (is_manual, body, env_vars) in scenarios.items()
    ]
    harness = (
        f"const jsCode = {json.dumps(js_code)};\n"
        f"const scenarios = {json.dumps(scenario_list)};\n"
        "const fn = new Function('$input', '$execution', '$vars', jsCode);\n"
        "const results = {};\n"
        "for (const s of scenarios) {\n"
        "  const $input = { first: () => ({ json: s.body }) };\n"
        "  const $execution = { mode: s.isManual ? 'manual' : 'webhook' };\n"
        "  const $vars = s.envVars;\n"
        "  results[s.name] = fn($input, $execution, $vars)[0].json;\n"
        "}\n"
        "console.log(JSON.stringify(results));"
    )
    result = subprocess.run(
        [_NODE_BINARY, "-e", harness], capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, f"Node execution failed: {result.stderr}"
    return json.loads(result.stdout)


@pytest.mark.skipif(_NODE_BINARY is None, reason="Node.js is not available - skipping code-execution contract tests")
class TestValidateBuildRequestExecution:
    """Correction V3, item 5 - actually executes 'Validate / Build
    Request' rather than only pattern-matching its source text, to
    genuinely prove its input validation/normalization and configuration
    gate behavior. Skipped (not failed) when no local Node.js binary is
    available, matching this file's existing "optional" pattern for
    environment-dependent checks (see TestOptionalLiveN8nImport)."""

    @pytest.fixture(scope="class")
    def results(self) -> dict[str, dict]:
        data = json.loads((_WORKFLOWS_DIR / _LIVE_RESEARCH_WORKFLOW_FILE).read_text(encoding="utf-8"))
        validate = next(n for n in data["nodes"] if n["name"] == "Validate / Build Request")
        js_code = validate["parameters"]["jsCode"]
        return _run_validate_build_request_scenarios(js_code, _VALIDATE_SCENARIOS)

    def test_whitespace_only_subject_raw_text_becomes_absent(self, results: dict[str, dict]) -> None:
        # NEWS_SCAN requires exactly one subject - a blank subject_raw_text
        # must never be silently treated as a provided one.
        result = results["whitespace_only_subject_raw_text"]
        assert "validationError" in result
        assert result["isManual"] is True

    def test_non_string_original_question_is_rejected(self, results: dict[str, dict]) -> None:
        assert "validationError" in results["non_string_original_question"]

    def test_whitespace_only_original_question_is_rejected(self, results: dict[str, dict]) -> None:
        assert "validationError" in results["whitespace_only_original_question"]

    # -- Final correction, item 1: safe input envelope ---------------------

    def test_null_body_returns_a_validation_error_and_does_not_throw(self, results: dict[str, dict]) -> None:
        result = results["null_body"]
        assert "validationError" in result
        assert result["isManual"] is False
        # The bounded message never echoes the raw (null) body.
        assert "null" not in result["validationError"].lower()

    def test_array_body_returns_a_validation_error(self, results: dict[str, dict]) -> None:
        result = results["array_body"]
        assert "validationError" in result
        assert result["isManual"] is False

    def test_string_body_returns_a_validation_error(self, results: dict[str, dict]) -> None:
        assert "validationError" in results["string_body"]

    def test_number_body_returns_a_validation_error(self, results: dict[str, dict]) -> None:
        assert "validationError" in results["number_body"]

    # -- Final correction, item 2: FINQUEST_API_BASE_URL/KEY_ID parsing ----

    def test_malformed_api_base_url_is_rejected(self, results: dict[str, dict]) -> None:
        result = results["malformed_api_base_url"]
        assert "validationError" in result
        assert "FINQUEST_API_BASE_URL" in result["validationError"]

    def test_api_base_url_without_a_hostname_is_rejected(self, results: dict[str, dict]) -> None:
        result = results["api_base_url_without_a_hostname"]
        assert "validationError" in result
        assert "hostname" in result["validationError"].lower()

    def test_api_base_url_with_embedded_credentials_is_rejected(self, results: dict[str, dict]) -> None:
        result = results["api_base_url_with_embedded_credentials"]
        assert "validationError" in result
        assert "credential" in result["validationError"].lower()

    def test_whitespace_surrounded_url_and_key_id_are_normalized(self, results: dict[str, dict]) -> None:
        result = results["whitespace_surrounded_url_and_key_id_are_normalized"]
        assert "validationError" not in result
        assert result["apiBaseUrl"] == "https://finquest.example.com"
        assert result["keyId"] == "key-123"

    def test_valid_normalized_input_still_reaches_trigger_finquest_job(self, results: dict[str, dict]) -> None:
        result = results["valid_normalized_input"]
        assert "validationError" not in result
        assert result["parameters"]["original_question"] == "What recent developments affect NVIDIA?"
        assert result["parameters"]["subject_raw_text"] == "NVIDIA Corporation"
        assert result["isManual"] is True
        assert result["jobType"] == "LIVE_RESEARCH_RUN_EXECUTION"
        assert result["apiBaseUrl"] == "https://finquest.example.com"
        assert result["keyId"] == "key-123"

    def test_missing_finquest_api_base_url_cannot_reach_the_job_post(self, results: dict[str, dict]) -> None:
        result = results["missing_finquest_api_base_url"]
        assert "validationError" in result
        assert "FINQUEST_API_BASE_URL" in result["validationError"]

    def test_missing_finquest_key_id_cannot_reach_the_job_post(self, results: dict[str, dict]) -> None:
        result = results["missing_finquest_key_id"]
        assert "validationError" in result
        assert "FINQUEST_KEY_ID" in result["validationError"]

    def test_production_requires_an_https_base_url(self, results: dict[str, dict]) -> None:
        result = results["production_non_https_base_url"]
        assert "validationError" in result
        assert result["isManual"] is False

    def test_manual_path_tolerates_a_non_https_base_url(self, results: dict[str, dict]) -> None:
        assert "validationError" not in results["manual_non_https_base_url"]


_CLASSIFY_SCENARIOS: dict[str, tuple[dict, dict]] = {
    # (trigger_response_item, validate_build_request_output)
    "successful_2xx_with_nested_job_id": (
        {"statusCode": 201, "headers": {}, "body": {"job": {"job_id": "job-abc-123"}}},
        {"isManual": False, "invocationId": _FIXED_UUID},
    ),
    "successful_2xx_with_flat_job_id_manual": (
        {"statusCode": 200, "headers": {}, "body": {"job_id": "job-xyz-789"}},
        {"isManual": True, "invocationId": _FIXED_UUID},
    ),
    "http_422_is_rejected": (
        {"statusCode": 422, "headers": {}, "body": {"detail": "original_question too short"}},
        {"isManual": False, "invocationId": _FIXED_UUID},
    ),
    "http_500_is_infra_failure": (
        {"statusCode": 500, "headers": {}, "body": "internal server error"},
        {"isManual": False, "invocationId": _FIXED_UUID},
    ),
    "transport_failure_has_no_status_code": (
        {"error": "connect ECONNREFUSED"},
        {"isManual": True, "invocationId": _FIXED_UUID},
    ),
    "2xx_without_a_job_id_is_infra_failure": (
        {"statusCode": 200, "headers": {}, "body": {"unexpected": "shape"}},
        {"isManual": False, "invocationId": _FIXED_UUID},
    ),
}


def _run_classify_trigger_response_scenarios(js_code: str, scenarios: dict[str, tuple[dict, dict]]) -> dict[str, dict]:
    """Executes 'Classify Trigger Response' in a single real Node.js
    subprocess against every named scenario, shimming both `$input` (the
    simulated Trigger FinQuest Job output) and `$('Validate / Build
    Request')` (Correction Final, item 4 - proves the 4xx/5xx/transport-
    failure classification end to end, not just by pattern-matching)."""
    scenario_list = [
        {"name": name, "item": item, "request": request}
        for name, (item, request) in scenarios.items()
    ]
    harness = (
        f"const jsCode = {json.dumps(js_code)};\n"
        f"const scenarios = {json.dumps(scenario_list)};\n"
        "const fn = new Function('$input', '$', jsCode);\n"
        "const results = {};\n"
        "for (const s of scenarios) {\n"
        "  const $input = { first: () => ({ json: s.item }) };\n"
        "  const $ = (name) => {\n"
        "    if (name === 'Validate / Build Request') { return { first: () => ({ json: s.request }) }; }\n"
        "    throw new Error('unexpected node reference: ' + name);\n"
        "  };\n"
        "  results[s.name] = fn($input, $)[0].json;\n"
        "}\n"
        "console.log(JSON.stringify(results));"
    )
    result = subprocess.run(
        [_NODE_BINARY, "-e", harness], capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, f"Node execution failed: {result.stderr}"
    return json.loads(result.stdout)


@pytest.mark.skipif(_NODE_BINARY is None, reason="Node.js is not available - skipping code-execution contract tests")
class TestClassifyTriggerResponseExecution:
    """Final correction, item 4 - actually executes 'Classify Trigger
    Response' to prove the ACCEPTED/REJECTED/INFRA_FAILURE classification
    of Trigger FinQuest Job's full HTTP response, rather than only
    pattern-matching its source text."""

    @pytest.fixture(scope="class")
    def results(self) -> dict[str, dict]:
        data = json.loads((_WORKFLOWS_DIR / _LIVE_RESEARCH_WORKFLOW_FILE).read_text(encoding="utf-8"))
        classify = next(n for n in data["nodes"] if n["name"] == "Classify Trigger Response")
        return _run_classify_trigger_response_scenarios(classify["parameters"]["jsCode"], _CLASSIFY_SCENARIOS)

    def test_a_successful_create_job_response_reaches_the_accepted_outcome(self, results: dict[str, dict]) -> None:
        result = results["successful_2xx_with_nested_job_id"]
        assert result["outcome"] == "ACCEPTED"
        assert result["jobId"] == "job-abc-123"
        assert result["isManual"] is False

    def test_a_successful_flat_job_id_response_reaches_the_accepted_outcome_on_the_manual_path(self, results: dict[str, dict]) -> None:
        result = results["successful_2xx_with_flat_job_id_manual"]
        assert result["outcome"] == "ACCEPTED"
        assert result["jobId"] == "job-xyz-789"
        assert result["isManual"] is True

    def test_a_simulated_http_422_routes_to_the_rejected_outcome(self, results: dict[str, dict]) -> None:
        result = results["http_422_is_rejected"]
        assert result["outcome"] == "REJECTED"
        assert result["statusCode"] == 422
        # JSON.stringify omits a key whose value is `undefined` entirely -
        # jobId is simply absent, not present-and-null, for a non-ACCEPTED
        # outcome.
        assert result.get("jobId") is None

    def test_a_simulated_http_500_routes_to_the_infra_failure_outcome(self, results: dict[str, dict]) -> None:
        result = results["http_500_is_infra_failure"]
        assert result["outcome"] == "INFRA_FAILURE"
        assert result["statusCode"] == 500

    def test_a_transport_failure_with_no_status_code_routes_to_the_infra_failure_outcome(self, results: dict[str, dict]) -> None:
        result = results["transport_failure_has_no_status_code"]
        assert result["outcome"] == "INFRA_FAILURE"
        assert result["statusCode"] is None

    def test_a_2xx_response_without_a_job_id_is_still_an_infra_failure_not_accepted(self, results: dict[str, dict]) -> None:
        result = results["2xx_without_a_job_id_is_infra_failure"]
        assert result["outcome"] == "INFRA_FAILURE"


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
