"""A structural (not byte-for-byte) OpenAPI stability snapshot: tags,
the path list, and the security-scheme names. Byte-for-byte snapshotting
would be too brittle across routine dependency bumps (FastAPI/Pydantic
version strings leak into generated schema details); this instead
locks in the *contract surface* - if a route is renamed, removed, or a
new one is added without updating this list, this test fails loudly
rather than silently drifting.
"""

from __future__ import annotations

from stock_research_core.api.app_factory import create_app

_EXPECTED_TAGS = {
    "Authentication", "Learners", "Curriculum", "Adaptive Learning", "Historical Scenarios",
    "Virtual Portfolios", "AI Tutor", "Administration", "Health", "Operations", "n8n Integration",
    "Quality Evaluation",
}

_EXPECTED_SECURITY_SCHEMES = {"HTTPBearer"}

_EXPECTED_PATHS = {
    "/health", "/ready",
    "/api/v1/auth/register", "/api/v1/auth/login", "/api/v1/auth/refresh", "/api/v1/auth/logout",
    "/api/v1/auth/logout-all", "/api/v1/auth/me",
    "/api/v1/learners/me", "/api/v1/learners/me/dashboard", "/api/v1/learners/me/mastery",
    "/api/v1/learners/me/progress", "/api/v1/learners/me/misconceptions",
    "/api/v1/learning-paths", "/api/v1/learning-paths/{path_id}", "/api/v1/learning-paths/{path_id}/modules",
    "/api/v1/modules/{module_id}", "/api/v1/modules/{module_id}/lessons",
    "/api/v1/lessons/{lesson_id}", "/api/v1/lessons/{lesson_id}/exercises",
    "/api/v1/exercises/{exercise_id}", "/api/v1/exercises/{exercise_id}/attempts", "/api/v1/attempts/{attempt_id}",
    "/api/v1/attempts/{attempt_id}/answers",
    "/api/v1/adaptive/sessions", "/api/v1/adaptive/sessions/{session_id}",
    "/api/v1/adaptive/sessions/{session_id}/next", "/api/v1/adaptive/sessions/{session_id}/complete",
    "/api/v1/adaptive/decisions/{decision_id}/accept", "/api/v1/adaptive/decisions/{decision_id}/start",
    "/api/v1/adaptive/decisions/{decision_id}/skip", "/api/v1/adaptive/decisions/{decision_id}/answers",
    "/api/v1/adaptive/diagnostics", "/api/v1/adaptive/diagnostics/{assessment_id}",
    "/api/v1/adaptive/diagnostics/{assessment_id}/items/{item_id}/start",
    "/api/v1/adaptive/diagnostics/{assessment_id}/items/{item_id}/result",
    "/api/v1/adaptive/diagnostics/{assessment_id}/complete",
    "/api/v1/scenarios", "/api/v1/scenarios/{scenario_id}", "/api/v1/scenarios/{scenario_id}/start",
    "/api/v1/scenarios/submissions/{submission_id}/submit", "/api/v1/scenarios/submissions/{submission_id}/reveal",
    "/api/v1/portfolios", "/api/v1/portfolios/{portfolio_id}", "/api/v1/portfolios/securities/{security_id}",
    "/api/v1/portfolios/{portfolio_id}/trades/preview", "/api/v1/portfolios/{portfolio_id}/trades",
    "/api/v1/portfolios/{portfolio_id}/transactions", "/api/v1/portfolios/{portfolio_id}/holdings",
    "/api/v1/portfolios/{portfolio_id}/journal", "/api/v1/portfolios/{portfolio_id}/valuations",
    "/api/v1/portfolios/{portfolio_id}/valuations/latest", "/api/v1/portfolios/{portfolio_id}/performance",
    "/api/v1/tutor/conversations", "/api/v1/tutor/conversations/{conversation_id}",
    "/api/v1/tutor/conversations/{conversation_id}/messages",
    "/api/v1/tutor/conversations/{conversation_id}/close",
    "/api/v1/admin/accounts", "/api/v1/admin/accounts/{account_id}",
    "/api/v1/admin/accounts/{account_id}/disable", "/api/v1/admin/accounts/{account_id}/enable",
    "/api/v1/admin/accounts/{account_id}/revoke-sessions",
    "/api/v1/admin/curriculum/skills", "/api/v1/admin/curriculum/paths",
    "/api/v1/admin/curriculum/paths/{path_id}/modules", "/api/v1/admin/curriculum/modules/{module_id}/lessons",
    "/api/v1/admin/curriculum/lessons/{lesson_id}/exercises",
    "/api/v1/admin/knowledge/ingest-curriculum", "/api/v1/admin/knowledge/documents",
    "/api/v1/admin/knowledge/ingestion-runs",
    "/api/v1/operations/jobs", "/api/v1/operations/jobs/{job_id}",
    "/api/v1/operations/jobs/{job_id}/cancel", "/api/v1/operations/jobs/{job_id}/requeue",
    "/api/v1/operations/metrics-summary",
    "/api/v1/integrations/n8n/jobs", "/api/v1/integrations/n8n/jobs/{job_id}",
    "/api/v1/integrations/n8n/jobs/{job_id}/events", "/api/v1/integrations/n8n/ready",
    "/api/v1/admin/evaluations/suites", "/api/v1/admin/evaluations/suites/import",
    "/api/v1/admin/evaluations/suites/{suite_id}", "/api/v1/admin/evaluations/suites/{suite_id}/approve",
    "/api/v1/admin/evaluations/suites/{suite_id}/archive",
    "/api/v1/admin/evaluations/runs", "/api/v1/admin/evaluations/runs/{run_id}",
    "/api/v1/admin/evaluations/runs/{run_id}/samples", "/api/v1/admin/evaluations/runs/{run_id}/metrics",
    "/api/v1/admin/evaluations/runs/{run_id}/compare", "/api/v1/admin/evaluations/runs/{run_id}/approve-baseline",
    "/api/v1/admin/evaluations/baselines", "/api/v1/admin/evaluations/baselines/{baseline_id}",
}


def _openapi_spec() -> dict:
    app = create_app(testing=True)
    return app.openapi()


def test_openapi_path_surface_matches_the_expected_contract() -> None:
    spec = _openapi_spec()
    actual_paths = set(spec["paths"].keys())
    missing = _EXPECTED_PATHS - actual_paths
    unexpected = actual_paths - _EXPECTED_PATHS
    assert not missing, f"expected paths missing from the API: {sorted(missing)}"
    assert not unexpected, f"undocumented new paths - update this snapshot deliberately: {sorted(unexpected)}"


def test_openapi_tags_match_the_expected_contract() -> None:
    spec = _openapi_spec()
    actual_tags: set[str] = set()
    for methods in spec["paths"].values():
        for operation in methods.values():
            actual_tags.update(operation.get("tags", []))
    assert actual_tags == _EXPECTED_TAGS


def test_openapi_declares_bearer_security_scheme() -> None:
    spec = _openapi_spec()
    schemes = set(spec.get("components", {}).get("securitySchemes", {}).keys())
    assert schemes == _EXPECTED_SECURITY_SCHEMES


def test_health_and_ready_are_unauthenticated_and_unversioned() -> None:
    spec = _openapi_spec()
    for path in ("/health", "/ready"):
        assert path in spec["paths"]
        get_operation = spec["paths"][path]["get"]
        assert not get_operation.get("security"), f"{path} must never require authentication"


def test_every_non_health_path_lives_under_the_versioned_prefix() -> None:
    spec = _openapi_spec()
    for path in spec["paths"]:
        if path in ("/health", "/ready"):
            continue
        assert path.startswith("/api/v1/"), f"{path} is missing the /api/v1 prefix"


def test_docs_can_be_disabled() -> None:
    from stock_research_core.api.settings import ApiSettings

    app = create_app(testing=True, api_settings=ApiSettings(api_docs_enabled=False))
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None
