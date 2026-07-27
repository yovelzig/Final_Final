"""Configuration for the embedding provider and tutor-model provider.

Reads settings from environment variables (and an optional `.env`
file), matching `infrastructure.database.config.DatabaseSettings`.
Importing this module never loads a model, opens a connection, or makes
a network request - it only describes how one *would* be configured.
"""

from __future__ import annotations

import math

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator

DEFAULT_EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_DIMENSION = 384

_SUPPORTED_TUTOR_MODEL_PROVIDERS = frozenset({"extractive", "openai_compatible", "ollama_cloud"})


class EmbeddingSettings(BaseSettings):
    """Which embedding provider to use and how to configure it."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    embedding_provider: str = "sentence_transformer"
    embedding_model_name: str = DEFAULT_EMBEDDING_MODEL_NAME
    embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION
    embedding_batch_size: int = 32


class TutorModelSettings(BaseSettings):
    """Which tutor-model provider to use and how to configure it.

    `tutor_model_provider="extractive"` (the default) requires no API
    key and no network access - it is the safe default described in the
    spec. `"openai_compatible"` requires the remaining fields.
    `"ollama_cloud"` (Phase D) calls Ollama Cloud's native
    `POST https://ollama.com/api/chat` endpoint directly and additionally
    requires a non-empty API key, a non-empty model name, and an HTTPS
    base URL. An unrecognized `tutor_model_provider` value fails
    configuration rather than silently falling back to `extractive`.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    tutor_model_provider: str = "extractive"
    tutor_model_base_url: str = "http://localhost:11434/v1"
    tutor_model_api_key: str = ""
    tutor_model_name: str = ""
    tutor_model_timeout_seconds: float = 60.0
    tutor_model_thinking_level: str = "low"

    @model_validator(mode="after")
    def _validate_provider_configuration(self) -> "TutorModelSettings":
        if self.tutor_model_provider not in _SUPPORTED_TUTOR_MODEL_PROVIDERS:
            raise ValueError(
                f"Unsupported tutor_model_provider {self.tutor_model_provider!r}; "
                f"must be one of {sorted(_SUPPORTED_TUTOR_MODEL_PROVIDERS)}"
            )
        if self.tutor_model_provider == "ollama_cloud":
            if not self.tutor_model_api_key:
                raise ValueError("tutor_model_api_key is required when tutor_model_provider='ollama_cloud'")
            if not self.tutor_model_name:
                raise ValueError("tutor_model_name is required when tutor_model_provider='ollama_cloud'")
            if not self.tutor_model_base_url.lower().startswith("https://"):
                raise ValueError(
                    "tutor_model_base_url must use https:// when tutor_model_provider='ollama_cloud'"
                )
        return self


DEFAULT_KNOWLEDGE_SUFFICIENCY_MIN_VECTOR_SCORE = 0.52
DEFAULT_KNOWLEDGE_SUFFICIENCY_MIN_LEXICAL_SCORE = 0.05
DEFAULT_KNOWLEDGE_SUFFICIENCY_MIN_CONTEXT_METADATA_SCORE = 0.90

_MIN_VECTOR_SCORE_BOUND = -1.0
_MAX_VECTOR_SCORE_BOUND = 1.0
_MIN_LEXICAL_SCORE_BOUND = 0.0
_MIN_METADATA_SCORE_BOUND = 0.0
_MAX_METADATA_SCORE_BOUND = 1.0


def _require_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")


class KnowledgeSufficiencySettings(BaseSettings):
    """Phase E1: whether/how the Knowledge Sufficiency Gate runs after
    retrieval and before any `TutorModelPort.generate()` call.

    `tutor_knowledge_sufficiency_gate_enabled=False` (the default, and
    production's current value) is the safe, rollback-neutral setting -
    deploying this code alone must not change existing behavior (any
    non-empty candidate list still reaches the model) until a separate,
    reviewed activation step flips this flag. The three threshold fields
    are only consulted when the gate is enabled; they were calibrated
    against the production corpus in Phase E0 (see
    docs/migration-status.md) and reject a non-finite or out-of-range
    value rather than silently clamping it.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    tutor_knowledge_sufficiency_gate_enabled: bool = False
    tutor_knowledge_sufficiency_min_vector_score: float = DEFAULT_KNOWLEDGE_SUFFICIENCY_MIN_VECTOR_SCORE
    tutor_knowledge_sufficiency_min_lexical_score: float = DEFAULT_KNOWLEDGE_SUFFICIENCY_MIN_LEXICAL_SCORE
    tutor_knowledge_sufficiency_min_context_metadata_score: float = (
        DEFAULT_KNOWLEDGE_SUFFICIENCY_MIN_CONTEXT_METADATA_SCORE
    )

    @model_validator(mode="after")
    def _validate_thresholds(self) -> "KnowledgeSufficiencySettings":
        _require_finite(
            "tutor_knowledge_sufficiency_min_vector_score", self.tutor_knowledge_sufficiency_min_vector_score
        )
        _require_finite(
            "tutor_knowledge_sufficiency_min_lexical_score", self.tutor_knowledge_sufficiency_min_lexical_score
        )
        _require_finite(
            "tutor_knowledge_sufficiency_min_context_metadata_score",
            self.tutor_knowledge_sufficiency_min_context_metadata_score,
        )
        if not (
            _MIN_VECTOR_SCORE_BOUND
            <= self.tutor_knowledge_sufficiency_min_vector_score
            <= _MAX_VECTOR_SCORE_BOUND
        ):
            raise ValueError(
                "tutor_knowledge_sufficiency_min_vector_score must be within "
                f"[{_MIN_VECTOR_SCORE_BOUND}, {_MAX_VECTOR_SCORE_BOUND}]"
            )
        if self.tutor_knowledge_sufficiency_min_lexical_score < _MIN_LEXICAL_SCORE_BOUND:
            raise ValueError(
                f"tutor_knowledge_sufficiency_min_lexical_score must be >= {_MIN_LEXICAL_SCORE_BOUND}"
            )
        if not (
            _MIN_METADATA_SCORE_BOUND
            <= self.tutor_knowledge_sufficiency_min_context_metadata_score
            <= _MAX_METADATA_SCORE_BOUND
        ):
            raise ValueError(
                "tutor_knowledge_sufficiency_min_context_metadata_score must be within "
                f"[{_MIN_METADATA_SCORE_BOUND}, {_MAX_METADATA_SCORE_BOUND}]"
            )
        return self
