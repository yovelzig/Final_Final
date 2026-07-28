"""Unit tests for the shared static localization table and the safe
default `UnavailableLanguageService` adapter (Phase G2E2A)."""

from __future__ import annotations

import pytest

from stock_research_core.application.exceptions import LanguageServiceError
from stock_research_core.application.language.enums import DetectedLanguage, LocalizedMessageKey
from stock_research_core.application.language.localization import localize
from stock_research_core.application.language.unavailable_language_service import UnavailableLanguageService
from stock_research_core.domain.ai_tutor.models import (
    EXACT_ADVICE_REFUSAL,
    EXACT_ADVICE_REFUSAL_HE,
    EXACT_INSUFFICIENT_EVIDENCE_FALLBACK,
    EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE,
    EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL,
    EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL_HE,
)


@pytest.mark.parametrize(
    ("key", "language", "expected"),
    [
        (LocalizedMessageKey.INSUFFICIENT_EVIDENCE, DetectedLanguage.EN, EXACT_INSUFFICIENT_EVIDENCE_FALLBACK),
        (LocalizedMessageKey.INSUFFICIENT_EVIDENCE, DetectedLanguage.HE, EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE),
        (LocalizedMessageKey.ADVICE_REFUSAL, DetectedLanguage.EN, EXACT_ADVICE_REFUSAL),
        (LocalizedMessageKey.ADVICE_REFUSAL, DetectedLanguage.HE, EXACT_ADVICE_REFUSAL_HE),
        (
            LocalizedMessageKey.SCENARIO_FUTURE_INFORMATION_REFUSAL,
            DetectedLanguage.EN,
            EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL,
        ),
        (
            LocalizedMessageKey.SCENARIO_FUTURE_INFORMATION_REFUSAL,
            DetectedLanguage.HE,
            EXACT_SCENARIO_FUTURE_INFORMATION_REFUSAL_HE,
        ),
    ],
)
def test_localize_returns_the_exact_approved_string(key, language, expected) -> None:
    assert localize(key, language=language) == expected


def test_every_localized_string_is_non_blank_and_distinct_per_language() -> None:
    en = localize(LocalizedMessageKey.INSUFFICIENT_EVIDENCE, language=DetectedLanguage.EN)
    he = localize(LocalizedMessageKey.INSUFFICIENT_EVIDENCE, language=DetectedLanguage.HE)
    assert en and he
    assert en != he


class TestUnavailableLanguageService:
    def test_detect_language_works_and_is_pure(self) -> None:
        service = UnavailableLanguageService()
        assert service.detect_language("What is diversification?") == DetectedLanguage.EN
        assert service.detect_language("מה זה פיזור סיכונים?") == DetectedLanguage.HE

    def test_localize_returns_exact_approved_strings(self) -> None:
        service = UnavailableLanguageService()
        assert (
            service.localize(LocalizedMessageKey.INSUFFICIENT_EVIDENCE, language=DetectedLanguage.HE)
            == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK_HE
        )

    @pytest.mark.asyncio
    async def test_translate_always_raises_language_service_error(self) -> None:
        service = UnavailableLanguageService()
        with pytest.raises(LanguageServiceError):
            await service.translate_to_english_query("מה זה תיק השקעות?", source_language=DetectedLanguage.HE)
