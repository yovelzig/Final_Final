"""Unit tests for `KnowledgeSufficiencySettings` (Phase E1).

Hermetic: `_env_file=None` is passed everywhere so a real local `.env`
(if one exists) can never leak into these tests, and every ambient
`TUTOR_KNOWLEDGE_SUFFICIENCY_*` OS environment variable is cleared first.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from stock_research_core.infrastructure.ai_tutor.config import KnowledgeSufficiencySettings

_KNOWLEDGE_SUFFICIENCY_ENV_VARS = (
    "TUTOR_KNOWLEDGE_SUFFICIENCY_GATE_ENABLED",
    "TUTOR_KNOWLEDGE_SUFFICIENCY_MIN_VECTOR_SCORE",
    "TUTOR_KNOWLEDGE_SUFFICIENCY_MIN_LEXICAL_SCORE",
    "TUTOR_KNOWLEDGE_SUFFICIENCY_MIN_CONTEXT_METADATA_SCORE",
)


@pytest.fixture(autouse=True)
def _clear_ambient_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _KNOWLEDGE_SUFFICIENCY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _settings(**overrides) -> KnowledgeSufficiencySettings:
    return KnowledgeSufficiencySettings(_env_file=None, **overrides)


class TestDefaults:
    def test_gate_disabled_by_default(self) -> None:
        settings = _settings()
        assert settings.tutor_knowledge_sufficiency_gate_enabled is False

    def test_default_thresholds_match_phase_e0_calibration(self) -> None:
        settings = _settings()
        assert settings.tutor_knowledge_sufficiency_min_vector_score == 0.52
        assert settings.tutor_knowledge_sufficiency_min_lexical_score == 0.05
        assert settings.tutor_knowledge_sufficiency_min_context_metadata_score == 0.90


class TestEnabling:
    def test_gate_can_be_explicitly_enabled(self) -> None:
        settings = _settings(tutor_knowledge_sufficiency_gate_enabled=True)
        assert settings.tutor_knowledge_sufficiency_gate_enabled is True

    def test_thresholds_can_be_overridden_while_enabled(self) -> None:
        settings = _settings(
            tutor_knowledge_sufficiency_gate_enabled=True,
            tutor_knowledge_sufficiency_min_vector_score=0.6,
            tutor_knowledge_sufficiency_min_lexical_score=0.1,
            tutor_knowledge_sufficiency_min_context_metadata_score=0.8,
        )
        assert settings.tutor_knowledge_sufficiency_min_vector_score == 0.6
        assert settings.tutor_knowledge_sufficiency_min_lexical_score == 0.1
        assert settings.tutor_knowledge_sufficiency_min_context_metadata_score == 0.8


class TestInvalidThresholdConfiguration:
    def test_nan_vector_threshold_rejected(self) -> None:
        with pytest.raises(ValidationError, match="tutor_knowledge_sufficiency_min_vector_score"):
            _settings(tutor_knowledge_sufficiency_min_vector_score=float("nan"))

    def test_infinite_lexical_threshold_rejected(self) -> None:
        with pytest.raises(ValidationError, match="tutor_knowledge_sufficiency_min_lexical_score"):
            _settings(tutor_knowledge_sufficiency_min_lexical_score=float("inf"))

    def test_negative_infinite_metadata_threshold_rejected(self) -> None:
        with pytest.raises(ValidationError, match="tutor_knowledge_sufficiency_min_context_metadata_score"):
            _settings(tutor_knowledge_sufficiency_min_context_metadata_score=float("-inf"))

    def test_out_of_range_vector_threshold_rejected(self) -> None:
        with pytest.raises(ValidationError, match="tutor_knowledge_sufficiency_min_vector_score"):
            _settings(tutor_knowledge_sufficiency_min_vector_score=1.5)

    def test_negative_lexical_threshold_rejected(self) -> None:
        with pytest.raises(ValidationError, match="tutor_knowledge_sufficiency_min_lexical_score"):
            _settings(tutor_knowledge_sufficiency_min_lexical_score=-0.01)

    def test_out_of_range_metadata_threshold_rejected(self) -> None:
        with pytest.raises(ValidationError, match="tutor_knowledge_sufficiency_min_context_metadata_score"):
            _settings(tutor_knowledge_sufficiency_min_context_metadata_score=1.01)

    def test_non_boolean_enabled_flag_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _settings(tutor_knowledge_sufficiency_gate_enabled="not-a-boolean")
