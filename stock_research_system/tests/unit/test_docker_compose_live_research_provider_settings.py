"""Unit tests (pure YAML parsing, no Docker required) confirming both
Compose files pass every supported G2A1 provider environment variable
through `finquest-worker-research` (G2B Correction V2, item 6/7).

Parses the raw YAML directly rather than shelling out to `docker compose
config` - no Docker daemon, network, or `AUTH_JWT_SECRET`-style required
variable needs to be available just to prove the settings are wired in
the compose file itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Every G2A1 provider setting (from `PerplexitySearchSettings`/
#: `SecEdgarSettings`) plus the G2B orchestration switch - the complete
#: set `finquest-worker-research` must pass through in both files.
_REQUIRED_PROVIDER_ENV_VARS = frozenset(
    {
        "LIVE_RESEARCH_JOBS_ENABLED",
        "LIVE_RESEARCH_PERPLEXITY_ENABLED",
        "LIVE_RESEARCH_PERPLEXITY_API_KEY",
        "LIVE_RESEARCH_PERPLEXITY_BASE_URL",
        "LIVE_RESEARCH_PERPLEXITY_TIMEOUT_SECONDS",
        "LIVE_RESEARCH_PERPLEXITY_MAX_RESULTS",
        "LIVE_RESEARCH_PERPLEXITY_MAX_TOKENS",
        "LIVE_RESEARCH_PERPLEXITY_MAX_TOKENS_PER_PAGE",
        "LIVE_RESEARCH_SEC_ENABLED",
        "LIVE_RESEARCH_SEC_USER_AGENT",
        "LIVE_RESEARCH_SEC_BASE_URL",
        "LIVE_RESEARCH_SEC_TIMEOUT_SECONDS",
        "LIVE_RESEARCH_SEC_REQUESTS_PER_SECOND",
    }
)


class _SafeLoaderIgnoringAnchor(yaml.SafeLoader):
    """`docker-compose.yml`'s `*worker-env` YAML anchor/merge-key
    (`<<: *worker-env`) parses fine under plain `yaml.safe_load` (PyYAML
    resolves anchors/aliases natively) - this loader exists only for
    clarity that no custom tag handling is required here."""


def _load_compose_service_environment(compose_filename: str, *, service_name: str) -> dict[str, object]:
    compose_path = _PROJECT_ROOT / compose_filename
    with compose_path.open("r", encoding="utf-8") as handle:
        document = yaml.load(handle, Loader=_SafeLoaderIgnoringAnchor)
    service = document["services"][service_name]
    environment = service["environment"]
    # Compose's `environment:` may be a mapping (used here) or a list of
    # "KEY=VALUE" strings - this repo's compose files use a mapping.
    assert isinstance(environment, dict), f"{compose_filename}:{service_name}.environment must be a mapping"
    return environment


@pytest.mark.parametrize("compose_filename", ["docker-compose.yml", "docker-compose.production.yml"])
class TestFinquestWorkerResearchProviderSettings:
    def test_every_required_provider_env_var_is_present(self, compose_filename: str) -> None:
        environment = _load_compose_service_environment(compose_filename, service_name="finquest-worker-research")
        missing = _REQUIRED_PROVIDER_ENV_VARS - set(environment)
        assert not missing, f"{compose_filename}: finquest-worker-research is missing {sorted(missing)}"

    def test_service_uses_the_finquest_research_queue(self, compose_filename: str) -> None:
        compose_path = _PROJECT_ROOT / compose_filename
        with compose_path.open("r", encoding="utf-8") as handle:
            document = yaml.load(handle, Loader=_SafeLoaderIgnoringAnchor)
        command = document["services"]["finquest-worker-research"]["command"]
        assert "finquest.research" in command

    def test_worker_env_anchor_fields_still_present_alongside_provider_settings(self, compose_filename: str) -> None:
        # Confirms the new provider keys were added *alongside* the
        # shared `*worker-env` anchor's own fields (DATABASE_URL etc.),
        # not as a replacement of it.
        environment = _load_compose_service_environment(compose_filename, service_name="finquest-worker-research")
        assert "DATABASE_URL" in environment
        assert "REDIS_URL" in environment


def test_dev_and_production_require_the_exact_same_provider_setting_names() -> None:
    dev_environment = _load_compose_service_environment("docker-compose.yml", service_name="finquest-worker-research")
    prod_environment = _load_compose_service_environment(
        "docker-compose.production.yml", service_name="finquest-worker-research"
    )
    dev_provider_keys = {key for key in dev_environment if key.startswith("LIVE_RESEARCH_")}
    prod_provider_keys = {key for key in prod_environment if key.startswith("LIVE_RESEARCH_")}
    assert dev_provider_keys == prod_provider_keys == _REQUIRED_PROVIDER_ENV_VARS
