"""Configuration for the embedding provider and tutor-model provider.

Reads settings from environment variables (and an optional `.env`
file), matching `infrastructure.database.config.DatabaseSettings`.
Importing this module never loads a model, opens a connection, or makes
a network request - it only describes how one *would* be configured.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_DIMENSION = 384


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
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    tutor_model_provider: str = "extractive"
    tutor_model_base_url: str = "http://localhost:11434/v1"
    tutor_model_api_key: str = ""
    tutor_model_name: str = ""
    tutor_model_timeout_seconds: float = 60.0
