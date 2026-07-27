"""Opt-in live integration check for `OllamaCloudTutorAdapter` (Phase D).

An external-provider network test, not a database-backed integration test -
it deliberately lives under `tests/live/`, not `tests/integration/`.
`tests/integration/conftest.py` declares autouse PostgreSQL migration and
table-cleanup fixtures that run for every test collected under that
directory regardless of marker; `tests/live/` has no `conftest.py` of its
own and no parent `tests/conftest.py` exists, so collecting or running this
file triggers no Alembic setup, no database connection attempt, and no
Redis/Docker dependency. `pytest tests/unit -q` never discovers it either.
It is still skipped by default: only a human operator explicitly setting
`OLLAMA_CLOUD_LIVE_TEST=1` *and* a real Ollama Cloud API key via
`OLLAMA_API_KEY` in the current shell enables it.

Builds the `TutorModelRequest` the same way production does - through
`GroundedTutorPromptBuilder`, not by hand. An earlier version of this test
constructed `TutorModelRequest` directly and put evidence only in
`structured_context`; neither `OllamaCloudTutorAdapter` nor
`OpenAICompatibleTutorAdapter` ever serializes `structured_context` itself -
only `GroundedTutorPromptBuilder` formats retrieved evidence, structured
context, and the "valid cited_chunk_ids for this question" allowlist into
`system_instructions`, which is the single place every provider gets that
framing from. That earlier version silently omitted the evidence from what
the model actually saw and failed structured-response validation after one
correction attempt - a test-fixture bug, not an adapter defect. Adapters
must not be changed to duplicate the prompt builder's formatting; this test
goes through the same production path (`GroundedTutorPromptBuilder`,
`TutorContext`, `TutorContextType.GENERAL_EDUCATION`) instead.

Never prints the API key, `message.thinking`, or the raw provider response -
only asserts on the strictly-parsed `TutorModelResult`.

Windows / corporate-TLS-inspection-proxy workstations only: if this
workstation's outbound HTTPS traffic is intercepted by a locally-trusted TLS
proxy (Windows trusts the proxy's root certificate, but Python's default
`certifi` bundle does not, so `httpx` fails with `CERTIFICATE_VERIFY_FAILED:
self-signed certificate in certificate chain` even though e.g. PowerShell
reaches the same endpoint fine), set an additional opt-in flag,
`OLLAMA_LIVE_USE_SYSTEM_TRUST=1`, to build the one HTTP client this test uses
from the OS trust store (via the `truststore` package - a dev/test-only
dependency, never used by application code and never `truststore
.inject_into_ssl()`-style global monkey-patching). This changes nothing about
`OllamaCloudTutorAdapter`'s own default TLS behavior - the adapter still
verifies against the standard `certifi` bundle whenever no client is
injected, exactly as in every other environment. `verify=False` is never
used.

Example (PowerShell, Windows):
    $env:OLLAMA_CLOUD_LIVE_TEST = "1"
    $env:OLLAMA_API_KEY = "<your Ollama Cloud API key>"
    $env:OLLAMA_LIVE_TEST_MODEL = "gpt-oss:20b"
    $env:OLLAMA_LIVE_USE_SYSTEM_TRUST = "1"
    python -m pytest tests/live/test_ollama_cloud_live.py -q -v
"""

from __future__ import annotations

import hashlib
import os
import ssl
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest

from stock_research_core.application.ai_tutor.models import RetrievalCandidate, TutorContext, TutorModelResult
from stock_research_core.application.ai_tutor.prompt_builder import GroundedTutorPromptBuilder
from stock_research_core.domain.ai_tutor.enums import (
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeSourceType,
    TutorContextType,
    TutorProviderType,
)
from stock_research_core.domain.ai_tutor.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from stock_research_core.infrastructure.ai_tutor.ollama_cloud_tutor import (
    DEFAULT_OLLAMA_CLOUD_BASE_URL,
    OllamaCloudTutorAdapter,
)

_LIVE_TEST_ENABLED = os.environ.get("OLLAMA_CLOUD_LIVE_TEST") == "1"
_LIVE_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
_LIVE_MODEL = os.environ.get("OLLAMA_LIVE_TEST_MODEL", "gpt-oss:20b")
_USE_SYSTEM_TRUST = os.environ.get("OLLAMA_LIVE_USE_SYSTEM_TRUST") == "1"

pytestmark = pytest.mark.skipif(
    not (_LIVE_TEST_ENABLED and _LIVE_API_KEY),
    reason=(
        "Opt-in only: set OLLAMA_CLOUD_LIVE_TEST=1 and OLLAMA_API_KEY in the shell "
        "to run this real Ollama Cloud call (optionally also "
        "OLLAMA_LIVE_USE_SYSTEM_TRUST=1 on a workstation behind a trusted TLS-inspection proxy)."
    ),
)


def _synthetic_candidate() -> RetrievalCandidate:
    now = datetime.now(timezone.utc)
    content = "Synthetic test evidence: a period's balance compounds when interest is reinvested."
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    source = KnowledgeSource(
        source_type=KnowledgeSourceType.LOCAL_MARKDOWN,
        title="Synthetic Live-Test Source",
        approval_status=KnowledgeApprovalStatus.APPROVED,
    )
    document = KnowledgeDocument(
        source_id=source.source_id, title="Synthetic Live-Test Document", content_text=content,
        content_hash=content_hash, status=KnowledgeDocumentStatus.PROCESSED,
        approval_status=KnowledgeApprovalStatus.APPROVED, available_at=now, parser_version="v1",
    )
    chunk = KnowledgeChunk(
        document_id=document.document_id, chunk_index=0, content=content, content_hash=content_hash,
        word_count=len(content.split()), estimated_token_count=len(content.split()) + 2,
        available_at=now, chunking_version="heading-word-chunker-v1",
    )
    return RetrievalCandidate(chunk=chunk, source=source, document=document, metadata_score=1.0, combined_score=1.0)


def _assert_result(result: TutorModelResult, candidate: RetrievalCandidate) -> None:
    assert result.answer_markdown.strip()
    assert result.cited_chunk_ids == [candidate.chunk.chunk_id]
    assert result.provider_type == TutorProviderType.OLLAMA_CLOUD
    assert result.model_name == _LIVE_MODEL
    assert not hasattr(result, "thinking")
    assert _LIVE_API_KEY not in result.model_dump_json()


class TestOllamaCloudLiveSmoke:
    """A single real call, using a synthetic UUID, synthetic evidence, and the
    production `GroundedTutorPromptBuilder` request-construction path only."""

    async def test_strict_json_and_citation_allowlisting_against_real_ollama_cloud(self) -> None:
        candidate = _synthetic_candidate()
        context = TutorContext(
            context_type=TutorContextType.GENERAL_EDUCATION,
            learner_id=uuid4(),
            structured_context={},
        )
        request = GroundedTutorPromptBuilder().build(
            question=(
                "According to the retrieved evidence, what happens when interest "
                "is reinvested?"
            ),
            conversation_messages=[],
            candidates=[candidate],
            context=context,
        )

        if _USE_SYSTEM_TRUST:
            # Dev/test-only: `truststore` is never imported by application
            # or library code (see pyproject.toml's `dev` extra) and this
            # never calls `truststore.inject_into_ssl()` - only a scoped
            # `SSLContext` for this one injected client. The client's
            # lifecycle belongs to this test (`async with`), never to the
            # adapter: `OllamaCloudTutorAdapter.aclose()` only closes a
            # client it constructed itself, so it is never expected to
            # close this injected one.
            import truststore

            ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            async with httpx.AsyncClient(verify=ssl_context) as client:
                adapter = OllamaCloudTutorAdapter(
                    base_url=DEFAULT_OLLAMA_CLOUD_BASE_URL,
                    api_key=_LIVE_API_KEY,
                    model_name=_LIVE_MODEL,
                    thinking_level="low",
                    client=client,
                )
                result = await adapter.generate(request)
                await adapter.aclose()  # no-op here: the client is injected, not adapter-owned
        else:
            # Default path, unchanged: the adapter builds and owns its own
            # `httpx.AsyncClient`, verifying against the standard `certifi`
            # bundle exactly as in every other environment.
            adapter = OllamaCloudTutorAdapter(
                base_url=DEFAULT_OLLAMA_CLOUD_BASE_URL,
                api_key=_LIVE_API_KEY,
                model_name=_LIVE_MODEL,
                thinking_level="low",
            )
            try:
                result = await adapter.generate(request)
            finally:
                await adapter.aclose()

        _assert_result(result, candidate)
