"""Phase 11 operational configuration: runtime environment / embedding
safety, Redis/Celery, metrics, tracing, worker readiness, and
trusted-proxy client identity.

Importing this module never opens a connection - it only describes how
one *would* be created, matching `infrastructure.database.config`.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic_settings import BaseSettings, SettingsConfigDict


class FinquestEnv(StrEnum):
    TEST = "test"
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class OperationsSettings(BaseSettings):
    """Runtime environment, embedding-provider production safety, Redis/
    Celery queue configuration, metrics, and optional OpenTelemetry tracing."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    finquest_env: FinquestEnv = FinquestEnv.DEVELOPMENT
    allow_fake_embeddings_in_production: bool = False

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    celery_worker_prefetch_multiplier: int = 1
    celery_task_acks_late: bool = True

    metrics_enabled: bool = True
    metrics_require_auth: bool = False

    otel_enabled: bool = False
    otel_service_name: str = "finquest-api"
    otel_exporter_otlp_endpoint: str = ""
    otel_sample_ratio: float = 0.1

    readiness_require_worker: bool = True
    readiness_require_redis: bool = True

    @property
    def resolved_celery_broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def resolved_celery_result_backend(self) -> str:
        if self.celery_result_backend:
            return self.celery_result_backend
        # Default to database index 1 so task-result bookkeeping never
        # shares a keyspace with broker delivery (database 0) - Celery's
        # own recommendation for a Redis broker + Redis result backend.
        return _with_db_index(self.redis_url, index=1)

    def is_fake_embedding_allowed(self) -> bool:
        if self.finquest_env in (FinquestEnv.TEST, FinquestEnv.DEVELOPMENT):
            return True
        return self.allow_fake_embeddings_in_production


class ProxySettings(BaseSettings):
    """Trusted-proxy-aware client identity configuration - see
    `infrastructure.identity.client_identity`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    trusted_proxy_cidrs: str = ""
    trust_forwarded_headers: bool = False

    @property
    def trusted_proxy_cidr_list(self) -> list[str]:
        return [cidr.strip() for cidr in self.trusted_proxy_cidrs.split(",") if cidr.strip()]


def _with_db_index(redis_url: str, *, index: int) -> str:
    base, _, _existing_index = redis_url.rpartition("/")
    if "/" not in redis_url or not base:
        return redis_url.rstrip("/") + f"/{index}"
    return f"{base}/{index}"
