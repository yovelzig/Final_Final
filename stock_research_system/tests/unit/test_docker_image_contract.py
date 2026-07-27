"""Contract tests for the Phase A2 Docker/Compose image-target and
worker-health changes. Pure text assertions against the repository's
`Dockerfile` and `docker-compose.production.yml` - no Docker, no PyYAML
dependency, no network access."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILE = (_REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
_PRODUCTION_COMPOSE = (_REPO_ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")
_DEV_COMPOSE = (_REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
_BACKUP_SCRIPT_PATH = _REPO_ROOT / "scripts" / "backup_production_database.sh"
_BACKUP_SCRIPT = _BACKUP_SCRIPT_PATH.read_text(encoding="utf-8")
_RUNBOOK = (_REPO_ROOT / "docs" / "production-deployment-runbook.md").read_text(encoding="utf-8")
_BASH = shutil.which("bash")

# Phase F1b/C3 integration: the seven S3 object-storage settings, added
# only to `finquest-api` (the only service that runs the operator
# `cli.knowledge_base --ingest-manifest` command today).
_S3_ENV_VAR_NAMES = (
    "OBJECT_STORAGE_PROVIDER", "AWS_REGION", "S3_BUCKET_NAME", "S3_KNOWLEDGE_PREFIX",
    "S3_EXTRACTED_TEXT_PREFIX", "S3_RESEARCH_ARTIFACT_PREFIX", "S3_FORCE_PATH_STYLE",
)
_NON_API_SERVICE_NAMES = (
    "finquest-web", "finquest-worker-market", "finquest-worker-portfolio",
    "finquest-worker-knowledge", "finquest-worker-default", "stock-db", "redis",
)


def _service_block_in(compose_text: str, service_name: str) -> str:
    pattern = rf"(?m)^  {re.escape(service_name)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)"
    match = re.search(pattern, compose_text, flags=re.DOTALL)
    assert match is not None, f"service block for {service_name!r} not found"
    return match.group(1)

_WORKER_TARGET_CONTRACT = {
    "finquest-api": "ai",
    "finquest-worker-knowledge": "ai",
    "finquest-worker-market": "base",
    "finquest-worker-portfolio": "base",
    "finquest-worker-default": "base",
}

_SERVICE_NAMES = (
    "finquest-api", "finquest-web", "finquest-worker-market", "finquest-worker-portfolio",
    "finquest-worker-knowledge", "finquest-worker-default", "stock-db", "redis",
)


def _service_block(service_name: str) -> str:
    """Slices the compose text between a top-level `  <service_name>:` header and the
    next top-level (2-space-indented) service header, so per-service assertions can't
    accidentally match another service's config."""
    pattern = rf"(?m)^  {re.escape(service_name)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)"
    match = re.search(pattern, _PRODUCTION_COMPOSE, flags=re.DOTALL)
    assert match is not None, f"service block for {service_name!r} not found in docker-compose.production.yml"
    return match.group(1)


class TestAiStageUsesPinnedCpuTorch:
    """Regression guard: `pip install ".[ai_tutor]"` alone resolves an unpinned,
    CUDA/NVIDIA-bundled torch wheel from PyPI's default index (~9GB of nvidia-*/triton
    packages the CPU-only production host can never use). The `ai` stage must install a
    pinned `+cpu` wheel from PyTorch's own CPU index first, so that requirement is
    already satisfied before `.[ai_tutor]` is installed."""

    def test_ai_stage_installs_a_pinned_cpu_torch_wheel_before_ai_tutor_extra(self) -> None:
        _, _, ai_stage = _DOCKERFILE.partition("FROM base AS ai")
        cpu_torch_match = re.search(r"pip install --no-cache-dir torch==\S+\+cpu\s", ai_stage)
        assert cpu_torch_match is not None, "ai stage must pin an explicit +cpu torch wheel"

        ai_tutor_index = ai_stage.find('".[ai_tutor]"')
        assert ai_tutor_index != -1, "ai stage must still install the ai_tutor extra"
        assert cpu_torch_match.start() < ai_tutor_index, (
            "the pinned CPU torch install must happen before .[ai_tutor], so pip never "
            "resolves the default (CUDA) torch wheel first"
        )

    def test_ai_stage_uses_the_official_pytorch_cpu_index(self) -> None:
        _, _, ai_stage = _DOCKERFILE.partition("FROM base AS ai")
        assert "--index-url https://download.pytorch.org/whl/cpu" in ai_stage


class TestDockerfileCopiesScripts:
    def test_dockerfile_copies_scripts_directory(self) -> None:
        assert "COPY scripts ./scripts" in _DOCKERFILE

    def test_scripts_copy_is_in_the_shared_base_stage(self) -> None:
        base_stage, _, ai_stage = _DOCKERFILE.partition("FROM base AS ai")
        assert "COPY scripts ./scripts" in base_stage
        assert "COPY scripts ./scripts" not in ai_stage


class TestDockerfileCopiesKnowledgeCorpus:
    """Phase F1b/C3 integration: both `base` and `ai` images must contain the
    version-controlled seed-knowledge corpus so `cli.knowledge_base
    --ingest-manifest` can find `knowledge/seed_documents/manifest.json`
    inside a deployed container."""

    def test_dockerfile_copies_knowledge_directory(self) -> None:
        assert "COPY knowledge ./knowledge" in _DOCKERFILE

    def test_knowledge_copy_is_in_the_shared_base_stage(self) -> None:
        base_stage, _, ai_stage = _DOCKERFILE.partition("FROM base AS ai")
        assert "COPY knowledge ./knowledge" in base_stage
        assert "COPY knowledge ./knowledge" not in ai_stage

    def test_knowledge_copy_precedes_the_chown(self) -> None:
        base_stage, _, _ = _DOCKERFILE.partition("FROM base AS ai")
        copy_index = base_stage.index("COPY knowledge ./knowledge")
        chown_index = base_stage.index("chown -R finquest:finquest /app")
        assert copy_index < chown_index

    def test_no_writable_knowledge_volume_or_bind_mount_introduced(self) -> None:
        assert "knowledge:/app/knowledge" not in _DEV_COMPOSE
        assert "knowledge:/app/knowledge" not in _PRODUCTION_COMPOSE
        assert "./knowledge:" not in _DEV_COMPOSE
        assert "./knowledge:" not in _PRODUCTION_COMPOSE


class TestComposeS3EnvironmentVariables:
    """Phase F1b/C3 integration: the seven S3 settings exist only on
    `finquest-api` in both Compose files - no Celery task consumes
    object storage yet, so no worker/web/database/redis service should
    carry them."""

    @pytest.mark.parametrize("compose_name,compose_text", [("dev", _DEV_COMPOSE), ("production", _PRODUCTION_COMPOSE)])
    def test_all_seven_variables_present_on_finquest_api(self, compose_name: str, compose_text: str) -> None:
        api_block = _service_block_in(compose_text, "finquest-api")
        for var_name in _S3_ENV_VAR_NAMES:
            assert re.search(rf"(?m)^\s+{var_name}:", api_block), (
                f"{var_name} missing from finquest-api in {compose_name} compose file"
            )

    @pytest.mark.parametrize("compose_name,compose_text", [("dev", _DEV_COMPOSE), ("production", _PRODUCTION_COMPOSE)])
    def test_no_s3_variable_present_on_other_services(self, compose_name: str, compose_text: str) -> None:
        for service_name in _NON_API_SERVICE_NAMES:
            block = _service_block_in(compose_text, service_name)
            for var_name in _S3_ENV_VAR_NAMES:
                assert not re.search(rf"(?m)^\s+{var_name}:", block), (
                    f"{var_name} unexpectedly present on {service_name} in {compose_name} compose file"
                )


_TUTOR_ENV_VAR_NAMES = (
    "TUTOR_MODEL_PROVIDER",
    "TUTOR_MODEL_BASE_URL",
    "TUTOR_MODEL_API_KEY",
    "TUTOR_MODEL_NAME",
    "TUTOR_MODEL_TIMEOUT_SECONDS",
    "TUTOR_MODEL_THINKING_LEVEL",
)


class TestComposeTutorModelEnvironmentVariables:
    """Phase D: all six generic tutor-model settings must reach
    `finquest-api` - the only service that constructs and calls the tutor
    model - in both Compose files, defaulting to the safe `extractive`
    provider with no key, and must not be added to any other service."""

    @pytest.mark.parametrize("compose_name,compose_text", [("dev", _DEV_COMPOSE), ("production", _PRODUCTION_COMPOSE)])
    def test_all_six_variables_present_on_finquest_api(self, compose_name: str, compose_text: str) -> None:
        api_block = _service_block_in(compose_text, "finquest-api")
        for var_name in _TUTOR_ENV_VAR_NAMES:
            assert re.search(rf"(?m)^\s+{var_name}:", api_block), (
                f"{var_name} missing from finquest-api in {compose_name} compose file"
            )

    @pytest.mark.parametrize("compose_name,compose_text", [("dev", _DEV_COMPOSE), ("production", _PRODUCTION_COMPOSE)])
    def test_no_tutor_variable_present_on_other_services(self, compose_name: str, compose_text: str) -> None:
        for service_name in _NON_API_SERVICE_NAMES:
            block = _service_block_in(compose_text, service_name)
            for var_name in _TUTOR_ENV_VAR_NAMES:
                assert not re.search(rf"(?m)^\s+{var_name}:", block), (
                    f"{var_name} unexpectedly present on {service_name} in {compose_name} compose file"
                )

    @pytest.mark.parametrize("compose_name,compose_text", [("dev", _DEV_COMPOSE), ("production", _PRODUCTION_COMPOSE)])
    def test_provider_defaults_to_extractive(self, compose_name: str, compose_text: str) -> None:
        api_block = _service_block_in(compose_text, "finquest-api")
        match = re.search(r"(?m)^\s+TUTOR_MODEL_PROVIDER:\s*\$\{TUTOR_MODEL_PROVIDER:-(\S+)\}", api_block)
        assert match is not None, f"TUTOR_MODEL_PROVIDER has no shell default in {compose_name} compose file"
        assert match.group(1) == "extractive", (
            f"TUTOR_MODEL_PROVIDER must default to extractive in {compose_name} compose file, "
            f"found {match.group(1)!r}"
        )

    @pytest.mark.parametrize("compose_name,compose_text", [("dev", _DEV_COMPOSE), ("production", _PRODUCTION_COMPOSE)])
    def test_api_key_has_no_real_secret_hardcoded(self, compose_name: str, compose_text: str) -> None:
        """`TUTOR_MODEL_API_KEY` must resolve to an empty string unless the
        operator sets a real key outside this committed file - never a
        literal secret value baked into the shell-default fallback."""
        api_block = _service_block_in(compose_text, "finquest-api")
        match = re.search(r'(?m)^\s+TUTOR_MODEL_API_KEY:\s*"?\$\{TUTOR_MODEL_API_KEY:-([^}]*)\}"?', api_block)
        assert match is not None, f"TUTOR_MODEL_API_KEY has no shell-default form in {compose_name} compose file"
        assert match.group(1) == "", (
            f"TUTOR_MODEL_API_KEY must default to empty in {compose_name} compose file, "
            f"found a hardcoded default {match.group(1)!r}"
        )


class TestProductionComposeBuildTargets:
    def test_every_service_target_matches_the_expected_contract(self) -> None:
        for service_name, expected_target in _WORKER_TARGET_CONTRACT.items():
            block = _service_block(service_name)
            match = re.search(r"target:\s*(\S+)", block)
            assert match is not None, f"{service_name} has no build target"
            assert match.group(1) == expected_target, (
                f"{service_name} expected target={expected_target!r}, found {match.group(1)!r}"
            )


class TestWorkerHealthchecks:
    def test_only_knowledge_worker_healthcheck_requires_embedding(self) -> None:
        for service_name in (
            "finquest-worker-market", "finquest-worker-portfolio", "finquest-worker-default",
        ):
            block = _service_block(service_name)
            healthcheck_test_line = re.search(r'healthcheck:\s*\n\s*test:.*', block)
            assert healthcheck_test_line is not None, f"{service_name} has no healthcheck test"
            assert "--require-embedding" not in healthcheck_test_line.group(0)

        knowledge_block = _service_block("finquest-worker-knowledge")
        knowledge_healthcheck = re.search(r'healthcheck:\s*\n\s*test:.*', knowledge_block)
        assert knowledge_healthcheck is not None
        assert "--require-embedding" in knowledge_healthcheck.group(0)


class TestHostBindingsUnchanged:
    def test_api_binding_unchanged(self) -> None:
        assert '"127.0.0.1:${API_HOST_PORT:-8080}:8080"' in _PRODUCTION_COMPOSE

    def test_web_binding_unchanged(self) -> None:
        assert '"127.0.0.1:${WEB_HOST_PORT:-3000}:3000"' in _PRODUCTION_COMPOSE

    def test_no_additional_host_port_bindings_introduced(self) -> None:
        bindings = re.findall(r'"127\.0\.0\.1:\$\{[A-Z_]+:-\d+\}:\d+"', _PRODUCTION_COMPOSE)
        assert set(bindings) == {
            '"127.0.0.1:${API_HOST_PORT:-8080}:8080"', '"127.0.0.1:${WEB_HOST_PORT:-3000}:3000"',
        }


class TestServiceAndContainerNamesUnchanged:
    def test_expected_service_names_are_all_present(self) -> None:
        for service_name in _SERVICE_NAMES:
            assert re.search(rf"(?m)^  {re.escape(service_name)}:\n", _PRODUCTION_COMPOSE), (
                f"service {service_name!r} missing from docker-compose.production.yml"
            )

    def test_container_names_match_service_names_for_backend_services(self) -> None:
        for service_name in (
            "finquest-api", "finquest-worker-market", "finquest-worker-portfolio",
            "finquest-worker-knowledge", "finquest-worker-default",
        ):
            block = _service_block(service_name)
            assert f"container_name: {service_name}" in block


class TestBackupScriptSignalHandling:
    """A trapped INT/TERM alone replaces Bash's default terminating behavior for
    those signals, so the script could in principle continue past an interrupt. EXIT
    must always run the guarded cleanup; INT/TERM must each terminate explicitly."""

    def test_exit_trap_runs_cleanup(self) -> None:
        assert re.search(r"^trap cleanup EXIT\s*$", _BACKUP_SCRIPT, flags=re.MULTILINE)

    def test_int_and_term_terminate_with_conventional_exit_codes(self) -> None:
        assert re.search(r"trap\s+'exit 130'\s+INT", _BACKUP_SCRIPT)
        assert re.search(r"trap\s+'exit 143'\s+TERM", _BACKUP_SCRIPT)

    def test_combined_non_terminating_trap_form_is_not_used(self) -> None:
        assert "trap cleanup EXIT INT TERM" not in _BACKUP_SCRIPT

    def test_tmp_file_cleared_only_after_the_successful_rename(self) -> None:
        mv_index = _BACKUP_SCRIPT.index('mv -n -- "${tmp_file}" "${final_file}"')
        clear_index = _BACKUP_SCRIPT.index('tmp_file=""', mv_index)
        assert clear_index > mv_index


class TestBackupScriptSourceCommit:
    def test_source_commit_flag_is_supported(self) -> None:
        assert "--source-commit" in _BACKUP_SCRIPT

    def test_default_source_commit_is_head(self) -> None:
        assert 'SOURCE_COMMIT_REF="HEAD"' in _BACKUP_SCRIPT

    def test_source_commit_is_resolved_and_validated_via_git_rev_parse(self) -> None:
        assert 'git rev-parse --verify "${SOURCE_COMMIT_REF}^{commit}"' in _BACKUP_SCRIPT

    def test_backup_filename_uses_the_resolved_commits_first_12_characters(self) -> None:
        assert 'commit_short="${resolved_commit:0:12}"' in _BACKUP_SCRIPT
        assert "${commit_short}" in _BACKUP_SCRIPT


class TestBackupScriptDirectorySafety:
    def test_resolves_repo_root_and_backup_dir_for_comparison(self) -> None:
        assert "git rev-parse --show-toplevel" in _BACKUP_SCRIPT
        assert "realpath -m" in _BACKUP_SCRIPT

    def test_rejects_backup_dir_inside_the_checkout(self) -> None:
        assert "is inside the Git checkout" in _BACKUP_SCRIPT

    def test_missing_value_arguments_exit_with_code_2(self) -> None:
        # Both option blocks must guard on a missing/empty value with `set -u`-safe
        # checks (`$# -lt 2` before ever expanding `$2`) and exit 2, not fall through
        # to an unbound-variable error.
        for option in ("--backup-dir", "--source-commit"):
            match = re.search(rf"{re.escape(option)}\)(.*?);;", _BACKUP_SCRIPT, flags=re.DOTALL)
            assert match is not None, f"no case block found for {option}"
            block = match.group(1)
            assert "$# -lt 2" in block, f"{option} block must guard on missing value before expanding $2"
            assert "exit 2" in block, f"{option} block must exit 2 on a missing/empty value"


@pytest.mark.skipif(_BASH is None, reason="bash not available on this host")
class TestBackupScriptStockDbHealthCheck:
    """Exercises the real stock-db health-check block verbatim (extracted, not
    reimplemented, so it can't drift from the actual logic) against a faked `dc()`
    function that echoes canned `docker compose ps` output - no real Docker,
    PostgreSQL, Redis, or network access."""

    @staticmethod
    def _extract_health_check_block() -> str:
        start = _BACKUP_SCRIPT.index("# 6) Only now access Docker and validate stock-db health.")
        end = _BACKUP_SCRIPT.index('mkdir -p "${resolved_backup_dir}"', start)
        block = _BACKUP_SCRIPT[start:end]
        assert "grep -qE '\\(healthy\\)'" in block, "health-check extraction markers drifted"
        return block

    def _run_health_check(self, *, fake_ps_output: str) -> subprocess.CompletedProcess[str]:
        harness = f"""#!/usr/bin/env bash
set -euo pipefail
dc() {{
  cat <<'FAKE_PS_OUTPUT'
{fake_ps_output}
FAKE_PS_OUTPUT
}}
{self._extract_health_check_block()}
echo "REACHED_PAST_HEALTH_CHECK"
"""
        return subprocess.run([_BASH, "-c", harness], capture_output=True, text=True, timeout=15)

    def test_unhealthy_status_is_rejected_with_exit_code_1(self) -> None:
        result = self._run_health_check(
            fake_ps_output="NAME       STATUS\nstock-db   Up 2 minutes (unhealthy)"
        )
        assert result.returncode == 1
        assert "not reporting healthy" in result.stderr

    def test_unhealthy_status_never_reaches_the_dump_step(self) -> None:
        result = self._run_health_check(
            fake_ps_output="NAME       STATUS\nstock-db   Up 2 minutes (unhealthy)"
        )
        assert "REACHED_PAST_HEALTH_CHECK" not in result.stdout

    def test_healthy_status_passes_the_health_check_stage(self) -> None:
        result = self._run_health_check(
            fake_ps_output="NAME       STATUS\nstock-db   Up 2 minutes (healthy)"
        )
        assert result.returncode == 0
        assert "REACHED_PAST_HEALTH_CHECK" in result.stdout


@pytest.fixture
def isolated_git_checkout():
    """A throwaway Git repository with one commit, containing neither `.env` nor
    `docker-compose.production.yml`.

    Deliberately created as a *sibling* of the real checkout (`dir=_REPO_ROOT.parent`)
    rather than via the OS default temp directory: on this project's Windows/Cygwin dev
    environment, the OS temp directory is reachable through two different Cygwin mount
    entries that don't cross-resolve, which can make `git rev-parse --show-toplevel`
    (drive-letter form) and a plain `realpath` (POSIX form via a different mount) disagree
    about a path that is actually the same location - an environment artifact, not a real
    bug. Reusing the checkout's own drive/mount for the temp repo sidesteps it entirely,
    on this host and on a plain Linux CI runner alike.

    This is what lets the source-commit and directory-safety tests below prove those
    paths run - and fail for the *right* reason - before the script ever looks for `.env`,
    independent of whether the machine running the suite happens to have one.
    """
    repo_dir = Path(tempfile.mkdtemp(prefix="a2-backup-script-repo-", dir=str(_REPO_ROOT.parent)))
    try:
        run = lambda *args: subprocess.run(  # noqa: E731
            args, cwd=repo_dir, capture_output=True, text=True, check=True,
        )
        run("git", "init", "-q")
        run("git", "config", "user.email", "test@example.invalid")
        run("git", "config", "user.name", "Test")
        (repo_dir / "README.md").write_text("placeholder\n", encoding="utf-8")
        run("git", "add", "README.md")
        run("git", "commit", "-q", "-m", "initial commit", "--no-verify")
        yield repo_dir
    finally:
        shutil.rmtree(repo_dir, ignore_errors=True)


@pytest.mark.skipif(_BASH is None, reason="bash not available on this host")
class TestBackupScriptArgumentValidationBehavior:
    """Actually invokes the script for the argument-validation and directory-safety
    paths only - all of which fail (by design) before any Docker/Postgres access is
    attempted, so these run without Docker, Postgres, Redis, or network access."""

    def _run(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [_BASH, str(_BACKUP_SCRIPT_PATH), *args],
            cwd=cwd, capture_output=True, text=True, timeout=15,
        )

    def test_help_exits_zero_and_does_not_leak_unrelated_command_output(self) -> None:
        result = self._run(_REPO_ROOT, "--help")
        assert result.returncode == 0
        assert "Usage:" in result.stdout
        # Regression guard: an earlier version had an unquoted heredoc with backticks
        # around prose ("`git pull`"), which bash's unquoted-heredoc command
        # substitution actually executed as part of printing --help.
        assert "tracking information" not in result.stdout
        assert result.stderr == ""

    def test_missing_backup_dir_value_exits_2(self) -> None:
        result = self._run(_REPO_ROOT, "--backup-dir")
        assert result.returncode == 2

    def test_missing_source_commit_value_exits_2(self) -> None:
        result = self._run(_REPO_ROOT, "--source-commit")
        assert result.returncode == 2

    def test_empty_backup_dir_value_exits_2(self) -> None:
        result = self._run(_REPO_ROOT, "--backup-dir", "")
        assert result.returncode == 2

    def test_backup_dir_inside_checkout_rejected_without_env_present(
        self, isolated_git_checkout: Path
    ) -> None:
        assert not (isolated_git_checkout / ".env").exists()
        result = self._run(isolated_git_checkout, "--backup-dir", "./some-subdir")
        assert result.returncode == 1
        assert "inside the Git checkout" in result.stderr
        assert "stock-db" not in result.stderr
        assert ".env" not in result.stderr

    def test_backup_dir_equal_to_checkout_root_rejected_without_env_present(
        self, isolated_git_checkout: Path
    ) -> None:
        result = self._run(isolated_git_checkout, "--backup-dir", ".")
        assert result.returncode == 1
        assert "inside the Git checkout" in result.stderr

    def test_invalid_source_commit_rejected_without_env_present(
        self, isolated_git_checkout: Path
    ) -> None:
        assert not (isolated_git_checkout / ".env").exists()
        result = self._run(isolated_git_checkout, "--source-commit", "not-a-real-ref-xyz")
        assert result.returncode == 1
        assert "does not resolve to a commit" in result.stderr
        assert "stock-db" not in result.stderr
        assert ".env" not in result.stderr

    def test_valid_commit_and_safe_dir_then_falls_through_to_missing_env(
        self, isolated_git_checkout: Path
    ) -> None:
        """Proves the ordering end to end: once source-commit resolution and
        directory-safety both pass, the very next failure is the missing `.env` - not
        a Docker/stock-db error - confirming `.env` is checked before Docker and after
        the two Git-only checks."""
        result = self._run(isolated_git_checkout, "--backup-dir", "/tmp/a2-test-safe-dir-xyz")
        assert result.returncode == 1
        assert ".env not found" in result.stderr
        assert "inside the Git checkout" not in result.stderr
        assert "does not resolve to a commit" not in result.stderr
        assert "stock-db" not in result.stderr


@pytest.mark.skipif(_BASH is None, reason="bash not available on this host")
class TestBackupScriptNeverOverwritesExistingBackup:
    """Exercises the real "final rename" block from the script directly - extracted
    verbatim (not re-implemented) so this test can't silently drift from the actual
    logic - against plain temp files, with no Docker/Postgres involved at all."""

    @staticmethod
    def _extract_rename_block() -> str:
        start = _BACKUP_SCRIPT.index("# 3) Only after verification succeeds")
        end = _BACKUP_SCRIPT.index('echo "Backup created:')
        block = _BACKUP_SCRIPT[start:end]
        assert 'mv -n -- "${tmp_file}" "${final_file}"' in block, "rename block extraction markers drifted"
        return block

    def _run_rename_block(self, *, tmp_file: Path, final_file: Path) -> subprocess.CompletedProcess[str]:
        # `.as_posix()` + single-quoting: a plain Windows backslash path embedded
        # unquoted into a bash script is mangled (bash treats `\` as an escape
        # character), and Git-Bash/MSYS2 correctly resolves forward-slash
        # "C:/..." absolute paths for filesystem operations regardless.
        harness = f"""#!/usr/bin/env bash
set -euo pipefail
tmp_file='{tmp_file.as_posix()}'
final_file='{final_file.as_posix()}'
{self._extract_rename_block()}
"""
        return subprocess.run([_BASH, "-c", harness], capture_output=True, text=True, timeout=15)

    def test_final_rename_succeeds_when_no_existing_backup(self, tmp_path: Path) -> None:
        tmp_file = tmp_path / "stock_db_20260101T000000Z_abc123456789.dump.tmp"
        final_file = tmp_path / "stock_db_20260101T000000Z_abc123456789.dump"
        tmp_file.write_text("dump-content", encoding="utf-8")

        result = self._run_rename_block(tmp_file=tmp_file, final_file=final_file)

        assert result.returncode == 0, result.stderr
        assert final_file.exists()
        assert final_file.read_text(encoding="utf-8") == "dump-content"
        assert not tmp_file.exists()

    def test_refuses_to_overwrite_an_existing_backup(self, tmp_path: Path) -> None:
        tmp_file = tmp_path / "stock_db_20260101T000000Z_abc123456789.dump.tmp"
        final_file = tmp_path / "stock_db_20260101T000000Z_abc123456789.dump"
        tmp_file.write_text("new-dump-content", encoding="utf-8")
        final_file.write_text("existing-backup-content", encoding="utf-8")

        result = self._run_rename_block(tmp_file=tmp_file, final_file=final_file)

        assert result.returncode != 0
        assert "refusing to overwrite" in result.stderr
        # The pre-existing backup must be untouched, and the new dump must still be on
        # disk (as tmp_file) so a caller's cleanup trap can find and remove only that -
        # never the file this test is protecting.
        assert final_file.read_text(encoding="utf-8") == "existing-backup-content"
        assert tmp_file.exists()
        assert tmp_file.read_text(encoding="utf-8") == "new-dump-content"


class TestRunbookFirstDeploymentOrdering:
    """The backup script is new in Phase A2 and doesn't exist on the pre-A2 commit,
    so the very first A2 deployment must pull before it can run the script, and must
    pass --source-commit so the backup is labeled with the still-running pre-deploy
    commit rather than the newly-pulled one."""

    def test_runbook_captures_pre_deploy_commit_before_pulling(self) -> None:
        assert 'PRE_DEPLOY_COMMIT="$(git rev-parse HEAD)"' in _RUNBOOK

    def test_runbook_passes_source_commit_to_the_backup_script(self) -> None:
        assert "--source-commit" in _RUNBOOK
        assert '"$PRE_DEPLOY_COMMIT"' in _RUNBOOK

    def test_pull_is_documented_before_the_backup_invocation(self) -> None:
        pull_index = _RUNBOOK.index("git pull --ff-only origin main")
        backup_index = _RUNBOOK.index("./scripts/backup_production_database.sh --source-commit")
        assert pull_index < backup_index
