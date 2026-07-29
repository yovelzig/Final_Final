"""Focused tests for the G2D2/H1 correction pass, section 7: the
production API and Coach worker images must actually install the
`openai` SDK the `OpenAIReasoningTutorAdapter`/research synthesis router
import - without pulling in the much heavier `quality_evaluation`/ragas
dependency group just to get it.

No real OpenAI service is ever called here - `OpenAIReasoningTutorAdapter.
_get_client()` only constructs an `AsyncOpenAI` client object (no network
I/O at construction time), so this proves importability/constructibility
only.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from stock_research_core.infrastructure.ai_tutor.openai_reasoning_tutor import OpenAIReasoningTutorAdapter

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT_TEXT = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
_PYPROJECT = tomllib.loads(_PYPROJECT_TEXT)
_DOCKERFILE = (_REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")


class TestOpenAiSdkIsImportableInThisEnvironment:
    """A real, unmocked import - proves the SDK is actually installed and
    importable, not merely declared in `pyproject.toml`."""

    def test_openai_package_imports(self) -> None:
        import openai

        assert openai.__version__

    def test_async_openai_client_symbol_is_available(self) -> None:
        from openai import AsyncOpenAI  # noqa: F401


class TestOpenAiReasoningAdapterConstructsWithoutModuleNotFoundError:
    def test_get_client_constructs_a_real_async_openai_client(self) -> None:
        adapter = OpenAIReasoningTutorAdapter(api_key="test-key-not-real", model_name="gpt-test")
        client = adapter._get_client()
        from openai import AsyncOpenAI

        assert isinstance(client, AsyncOpenAI)

    def test_get_client_is_idempotent(self) -> None:
        adapter = OpenAIReasoningTutorAdapter(api_key="test-key-not-real", model_name="gpt-test")
        first = adapter._get_client()
        second = adapter._get_client()
        assert first is second


class TestOpenAiIsItsOwnSmallDependencyExtra:
    """`openai` must be its own extra, separate from `quality_evaluation`
    - installing it must never require ragas/langchain-community."""

    def test_openai_extra_exists_and_contains_only_the_openai_sdk(self) -> None:
        extras = _PYPROJECT["project"]["optional-dependencies"]
        assert "openai" in extras
        openai_extra = extras["openai"]
        assert any(dep.startswith("openai") for dep in openai_extra)
        assert not any("ragas" in dep or "langchain" in dep for dep in openai_extra)

    def test_quality_evaluation_extra_is_untouched_and_still_heavier(self) -> None:
        extras = _PYPROJECT["project"]["optional-dependencies"]
        quality_evaluation_extra = extras["quality_evaluation"]
        assert any("ragas" in dep for dep in quality_evaluation_extra)
        assert any("langchain-community" in dep for dep in quality_evaluation_extra)


class TestDockerfileInstallsTheOpenAiExtraInTheSharedBaseStage:
    """`finquest-api` builds on the `ai` stage (`FROM base AS ai`) and
    `finquest-worker-coach` builds on `base` by default - installing
    `.[openai]` in `base` covers both without installing ragas."""

    def test_base_stage_installs_the_openai_extra(self) -> None:
        base_stage, _, _ = _DOCKERFILE.partition("FROM base AS ai")
        assert re.search(r'pip install --no-cache-dir\s+".\[openai\]"', base_stage)

    def test_base_stage_does_not_install_quality_evaluation(self) -> None:
        """Checks the actual `pip install` invocations, not comment text
        (this file's own Dockerfile comments legitimately mention
        `quality_evaluation` by name when explaining why it's excluded)."""
        install_lines = re.findall(r"pip install --no-cache-dir[^\n]*", _DOCKERFILE)
        assert not any("quality_evaluation" in line or "ragas" in line for line in install_lines)
