"""Unit tests for `application.language.localized_messages`."""

from __future__ import annotations

import pytest

from stock_research_core.application.language.detection import Language
from stock_research_core.application.language.localized_messages import LocalizedMessageKey, localized_message
from stock_research_core.domain.ai_tutor.models import EXACT_ADVICE_REFUSAL, EXACT_INSUFFICIENT_EVIDENCE_FALLBACK


@pytest.mark.parametrize("key", list(LocalizedMessageKey))
def test_every_key_has_both_languages(key: LocalizedMessageKey) -> None:
    english = localized_message(key, language=Language.ENGLISH)
    hebrew = localized_message(key, language=Language.HEBREW)
    assert english.strip()
    assert hebrew.strip()
    assert english != hebrew


def test_insufficient_material_reuses_the_exact_english_fallback_constant() -> None:
    assert (
        localized_message(LocalizedMessageKey.INSUFFICIENT_MATERIAL, language=Language.ENGLISH)
        == EXACT_INSUFFICIENT_EVIDENCE_FALLBACK
    )


def test_unsafe_advice_reuses_the_exact_english_refusal_constant() -> None:
    assert (
        localized_message(LocalizedMessageKey.UNSAFE_INVESTMENT_ADVICE, language=Language.ENGLISH)
        == EXACT_ADVICE_REFUSAL
    )
