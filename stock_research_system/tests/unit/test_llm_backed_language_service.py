"""Unit tests for `LlmBackedLanguageService` (Phase G2E2A).

Every request goes through an injected `httpx.AsyncClient` built on
`httpx.MockTransport` - no real network access and no live call to any
translation endpoint is ever made in this file.
"""

from __future__ import annotations

import json

import httpx
import pytest

from stock_research_core.application.exceptions import LanguageServiceError
from stock_research_core.application.language.enums import DetectedLanguage, LocalizedMessageKey
from stock_research_core.application.language.models import (
    MAX_TRANSLATED_QUERY_LENGTH,
    MAX_TRANSLATION_INPUT_LENGTH,
)
from stock_research_core.domain.ai_tutor.models import EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE
from stock_research_core.infrastructure.language.llm_backed_language_service import LlmBackedLanguageService

_FAKE_API_KEY = "sk-test-only-not-a-real-secret-abc123"


def _client_for(responses: list) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    captured: list[httpx.Request] = []
    state = {"index": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        index = state["index"]
        state["index"] += 1
        result = responses[index]
        if isinstance(result, Exception):
            raise result
        return result

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client, captured


def _make_adapter(client: httpx.AsyncClient, **overrides) -> LlmBackedLanguageService:
    kwargs = {
        "base_url": "https://example-llm.internal/v1",
        "api_key": _FAKE_API_KEY,
        "model_name": "test-model",
        "client": client,
    }
    kwargs.update(overrides)
    return LlmBackedLanguageService(**kwargs)


def _completion_response(query: str) -> httpx.Response:
    body = {
        "id": "resp-1",
        "choices": [{"message": {"role": "assistant", "content": json.dumps({"query": query})}}],
    }
    return httpx.Response(200, json=body)


class TestDetectAndLocalize:
    def test_detect_language_is_pure_and_never_calls_the_network(self) -> None:
        client, captured = _client_for([])
        adapter = _make_adapter(client)
        assert adapter.detect_language("מה זה תיק השקעות?") == DetectedLanguage.HE
        assert captured == []

    def test_localize_returns_exact_approved_hebrew_string(self) -> None:
        client, _captured = _client_for([])
        adapter = _make_adapter(client)
        assert (
            adapter.localize(LocalizedMessageKey.INSUFFICIENT_EVIDENCE, language=DetectedLanguage.HE)
            == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE
        )


class TestTranslateToEnglishQuery:
    async def test_successful_translation_returns_bounded_query(self) -> None:
        client, captured = _client_for([_completion_response("diversification portfolio risk")])
        adapter = _make_adapter(client)

        result = await adapter.translate_to_english_query(
            "מה זה פיזור סיכונים בתיק השקעות?", source_language=DetectedLanguage.HE
        )

        assert result.translated_query == "diversification portfolio risk"
        assert result.source_language == DetectedLanguage.HE
        assert len(captured) == 1

    async def test_request_uses_translate_only_system_prompt_never_the_tutors_own(self) -> None:
        client, captured = _client_for([_completion_response("diversification")])
        adapter = _make_adapter(client)

        await adapter.translate_to_english_query("מה זה פיזור סיכונים?", source_language=DetectedLanguage.HE)

        payload = json.loads(captured[0].content)
        system_message = payload["messages"][0]["content"]
        assert "translate" in system_message.lower()
        assert "FinQuest" not in system_message  # never the tutor's own system_instructions

    async def test_bearer_authorization_header(self) -> None:
        client, captured = _client_for([_completion_response("diversification")])
        adapter = _make_adapter(client)

        await adapter.translate_to_english_query("מה זה פיזור סיכונים?", source_language=DetectedLanguage.HE)

        assert captured[0].headers["authorization"] == f"Bearer {_FAKE_API_KEY}"

    async def test_malformed_json_content_raises_language_service_error(self) -> None:
        body = {"choices": [{"message": {"content": "not json"}}]}
        client, _captured = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        with pytest.raises(LanguageServiceError):
            await adapter.translate_to_english_query("מה זה פיזור סיכונים?", source_language=DetectedLanguage.HE)

    async def test_missing_query_field_raises_language_service_error(self) -> None:
        body = {"choices": [{"message": {"content": json.dumps({"unexpected": "shape"})}}]}
        client, _captured = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        with pytest.raises(LanguageServiceError):
            await adapter.translate_to_english_query("מה זה פיזור סיכונים?", source_language=DetectedLanguage.HE)

    async def test_empty_query_field_raises_language_service_error(self) -> None:
        body = {"choices": [{"message": {"content": json.dumps({"query": "   "})}}]}
        client, _captured = _client_for([httpx.Response(200, json=body)])
        adapter = _make_adapter(client)

        with pytest.raises(LanguageServiceError):
            await adapter.translate_to_english_query("מה זה פיזור סיכונים?", source_language=DetectedLanguage.HE)

    async def test_http_error_response_raises_language_service_error(self) -> None:
        client, _captured = _client_for([httpx.Response(400, json={"error": "bad request"})])
        adapter = _make_adapter(client)

        with pytest.raises(LanguageServiceError):
            await adapter.translate_to_english_query("מה זה פיזור סיכונים?", source_language=DetectedLanguage.HE)

    async def test_non_json_response_raises_language_service_error(self) -> None:
        client, _captured = _client_for([httpx.Response(200, content=b"not json at all")])
        adapter = _make_adapter(client)

        with pytest.raises(LanguageServiceError):
            await adapter.translate_to_english_query("מה זה פיזור סיכונים?", source_language=DetectedLanguage.HE)

    async def test_transient_error_retried_then_succeeds(self) -> None:
        client, captured = _client_for(
            [httpx.Response(503), _completion_response("diversification")]
        )
        adapter = _make_adapter(client)

        result = await adapter.translate_to_english_query("מה זה פיזור סיכונים?", source_language=DetectedLanguage.HE)

        assert result.translated_query == "diversification"
        assert len(captured) == 2

    async def test_transport_error_raises_language_service_error_never_a_raw_exception(self) -> None:
        client, _captured = _client_for(
            [httpx.ConnectError("boom"), httpx.ConnectError("boom"), httpx.ConnectError("boom")]
        )
        adapter = _make_adapter(client)

        with pytest.raises(LanguageServiceError):
            await adapter.translate_to_english_query("מה זה פיזור סיכונים?", source_language=DetectedLanguage.HE)

    async def test_aclose_closes_owned_client_only(self) -> None:
        client, _captured = _client_for([])
        adapter = _make_adapter(client)
        # Adapter was given an externally-owned client - aclose() must not close it.
        await adapter.aclose()
        assert not client.is_closed


class TestStrictTranslationResultValidation:
    """Phase G2E2A req. 7: the provider's response must be exactly
    `{"query": "..."}`.

    Every rejection below must surface as `LanguageServiceError` and
    nothing else - a raw `pydantic.ValidationError`, `KeyError`, or
    `json.JSONDecodeError` escaping this adapter would break every
    caller's fail-closed handling, which catches `LanguageServiceError`
    specifically. None of these messages may contain the provider's raw
    response either (asserted by
    `test_no_rejection_message_echoes_the_raw_provider_content`)."""

    def _adapter_for_content(self, content: object) -> LlmBackedLanguageService:
        body = {"choices": [{"message": {"content": content}}]}
        client, _captured = _client_for([httpx.Response(200, json=body)])
        return _make_adapter(client)

    async def _expect_rejection(self, content: object) -> LanguageServiceError:
        adapter = self._adapter_for_content(content)
        with pytest.raises(LanguageServiceError) as exc_info:
            await adapter.translate_to_english_query(
                "מה זה פיזור סיכונים?", source_language=DetectedLanguage.HE
            )
        return exc_info.value

    async def test_extra_key_alongside_query_is_rejected(self) -> None:
        """`extra="forbid"`: a model that also returns the *tutor's* own
        response shape must not be accepted as a translation."""
        await self._expect_rejection(json.dumps({"query": "diversification", "answer_markdown": "..."}))

    async def test_non_string_query_is_rejected(self) -> None:
        await self._expect_rejection(json.dumps({"query": ["diversification"]}))

    async def test_null_query_is_rejected(self) -> None:
        await self._expect_rejection(json.dumps({"query": None}))

    async def test_query_longer_than_the_configured_bound_is_rejected(self) -> None:
        """Rejected outright rather than silently truncated: a response
        that long is not a search query, and truncating it would invent a
        query the provider never returned."""
        await self._expect_rejection(json.dumps({"query": "x" * (MAX_TRANSLATED_QUERY_LENGTH + 1)}))

    async def test_query_exactly_at_the_bound_is_accepted(self) -> None:
        """The bound is inclusive - proves the rejection above is about
        exceeding the limit, not about long-but-legal queries."""
        at_bound = "x" * MAX_TRANSLATED_QUERY_LENGTH
        client, _captured = _client_for([_completion_response(at_bound)])
        adapter = _make_adapter(client)

        result = await adapter.translate_to_english_query(
            "שאלה ארוכה מאוד", source_language=DetectedLanguage.HE
        )

        assert result.translated_query == at_bound

    async def test_still_hebrew_output_is_rejected(self) -> None:
        """A structurally perfect response that did not actually translate
        is a failure: passing Hebrew on to an English-only retriever is
        exactly what this bridge exists to prevent."""
        await self._expect_rejection(json.dumps({"query": "מה זה פיזור סיכונים"}))

    async def test_markdown_code_fenced_output_is_rejected(self) -> None:
        await self._expect_rejection('```json\n{"query": "diversification"}\n```')

    async def test_full_answer_shaped_output_is_rejected(self) -> None:
        """A model that ignores "do not answer" and returns prose instead
        of the JSON object must never have that prose used as a query."""
        await self._expect_rejection(
            "Diversification is the practice of spreading investments across assets to reduce risk."
        )

    async def test_json_array_instead_of_object_is_rejected(self) -> None:
        await self._expect_rejection(json.dumps([{"query": "diversification"}]))

    async def test_json_scalar_instead_of_object_is_rejected(self) -> None:
        await self._expect_rejection(json.dumps("diversification"))

    async def test_empty_content_is_rejected(self) -> None:
        await self._expect_rejection("")

    async def test_non_string_content_is_rejected(self) -> None:
        """A provider that returns a structured `content` (list of parts,
        object, ...) instead of a string must be rejected, not coerced."""
        await self._expect_rejection([{"type": "text", "text": '{"query": "diversification"}'}])

    async def test_missing_choices_is_rejected(self) -> None:
        client, _captured = _client_for([httpx.Response(200, json={"id": "resp-1"})])
        adapter = _make_adapter(client)

        with pytest.raises(LanguageServiceError):
            await adapter.translate_to_english_query(
                "מה זה פיזור סיכונים?", source_language=DetectedLanguage.HE
            )

    async def test_no_rejection_message_echoes_the_raw_provider_content(self) -> None:
        secret_looking_content = json.dumps(
            {"query": "diversification", "leaked_internal_field": "provider-internal-value-xyz"}
        )
        error = await self._expect_rejection(secret_looking_content)

        assert "provider-internal-value-xyz" not in str(error)
        assert "leaked_internal_field" not in str(error)

    async def test_original_text_sent_to_the_provider_is_bounded(self) -> None:
        """Req. 7's input bound: the adapter never forwards an unbounded
        learner message to the provider, independent of any upstream
        caller's own limit."""
        client, captured = _client_for([_completion_response("diversification")])
        adapter = _make_adapter(client)

        await adapter.translate_to_english_query("ש" * 9000, source_language=DetectedLanguage.HE)

        sent_user_message = json.loads(captured[0].content)["messages"][1]["content"]
        assert len(sent_user_message) == MAX_TRANSLATION_INPUT_LENGTH


class TestOllamaCloudWireShapeSharesTheSameValidation:
    """One adapter, two wire shapes - never a second `LanguageServicePort`
    implementation per provider, and never a second (weaker) validator."""

    def _ollama_adapter(self, responses: list) -> tuple[LlmBackedLanguageService, list[httpx.Request]]:
        client, captured = _client_for(responses)
        return _make_adapter(client, wire_shape="ollama_cloud"), captured

    async def test_successful_translation_reads_the_native_message_shape(self) -> None:
        body = {"message": {"role": "assistant", "content": json.dumps({"query": "diversification"})}}
        adapter, captured = self._ollama_adapter([httpx.Response(200, json=body)])

        result = await adapter.translate_to_english_query(
            "מה זה פיזור סיכונים?", source_language=DetectedLanguage.HE
        )

        assert result.translated_query == "diversification"
        assert captured[0].url.path.endswith("/chat")

    async def test_openai_shaped_response_is_rejected_on_the_native_wire_shape(self) -> None:
        adapter, _captured = self._ollama_adapter([_completion_response("diversification")])

        with pytest.raises(LanguageServiceError):
            await adapter.translate_to_english_query(
                "מה זה פיזור סיכונים?", source_language=DetectedLanguage.HE
            )

    async def test_still_hebrew_output_is_rejected_on_the_native_wire_shape(self) -> None:
        body = {"message": {"content": json.dumps({"query": "מה זה פיזור סיכונים"})}}
        adapter, _captured = self._ollama_adapter([httpx.Response(200, json=body)])

        with pytest.raises(LanguageServiceError):
            await adapter.translate_to_english_query(
                "מה זה פיזור סיכונים?", source_language=DetectedLanguage.HE
            )

    async def test_unsupported_wire_shape_is_rejected_at_construction(self) -> None:
        client, _captured = _client_for([])
        with pytest.raises(ValueError):
            _make_adapter(client, wire_shape="not_a_real_wire_shape")
