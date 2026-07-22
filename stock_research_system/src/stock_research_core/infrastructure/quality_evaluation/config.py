"""Phase 13 quality-evaluation configuration (spec sections 4, 15, 18,
27). Importing this module never opens a connection, never downloads a
model, and never creates an HTTP client - it only describes how the
platform *would* be configured, matching `infrastructure.
learning_orchestrator.config`/`infrastructure.operations.config`.

`ragas_enabled` defaults to `False`: DETERMINISTIC mode is fully
functional with no evaluator LLM and no API key required.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class QualityEvaluationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    quality_evaluation_mode: str = "DETERMINISTIC"

    ragas_enabled: bool = False
    ragas_evaluator_provider: str = "openai_compatible"
    ragas_evaluator_base_url: str = ""
    ragas_evaluator_api_key: str = ""
    ragas_evaluator_model: str = ""
    ragas_embedding_provider: str = "existing_finquest"
    ragas_max_concurrency: int = 2
    ragas_timeout_seconds: int = 120
    ragas_max_retries: int = 2
    ragas_max_samples_per_run: int = 200
    ragas_cache_enabled: bool = True
    #: Reject same-model evaluation by default (spec section 4) - the
    #: tutor's own model must not also grade itself unless explicitly
    #: overridden after conscious review.
    ragas_allow_same_model_as_tutor: bool = False

    quality_gate_default_absolute_tolerance: float = 0.02
    quality_gate_default_relative_tolerance: float = 0.05

    learning_quality_min_cohort_size: int = 5
    learning_quality_min_retention_days: int = 7
    learning_quality_max_retention_days: int = 60

    #: Production startup must not silently enable production-sample
    #: capture into evaluation datasets (spec section 27).
    quality_allow_production_sample_capture: bool = False
