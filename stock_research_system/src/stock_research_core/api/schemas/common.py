"""Shared API DTOs: the error envelope and generic pagination wrapper."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ApiSchema(BaseModel):
    """Base class for every API DTO. Rejects unknown fields on input."""

    model_config = ConfigDict(extra="forbid")


class ApiErrorDetail(ApiSchema):
    """One field-level or general validation detail within an `ApiError`."""

    field: str | None = Field(default=None, description="The offending field path, if applicable.")
    message: str = Field(description="A safe, English, human-readable explanation.")


class ApiErrorBody(ApiSchema):
    code: str = Field(description="A stable, machine-readable error code, e.g. AUTHENTICATION_FAILED.")
    message: str = Field(description="A safe English message. Never a stack trace or SQL.")
    details: list[ApiErrorDetail] = Field(default_factory=list)
    correlation_id: str = Field(description="Echoes the request's X-Correlation-ID.")


class ApiError(ApiSchema):
    """The FinQuest API's consistent error envelope."""

    error: ApiErrorBody


class PaginationMeta(ApiSchema):
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    returned: int = Field(ge=0)
    total: int = Field(ge=0)


class PaginatedResponse(ApiSchema, Generic[T]):
    """A generic `{"items": [...], "pagination": {...}}` envelope."""

    items: list[T]
    pagination: PaginationMeta
