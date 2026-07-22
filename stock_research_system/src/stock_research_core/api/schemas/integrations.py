"""Request/response DTOs for `/api/v1/integrations/n8n`.

`IntegrationJobRequest.parameters` is a plain JSON object at the schema
layer, but is never accepted as "unvalidated arbitrary JSON" - it is
always parsed against the job type's registered parameter model
(`application.operations.job_registry`) before a job is created, exactly
like the admin `CreateJobRequest`. No integration credential (key ID,
raw key, or key hash) is ever included in a response schema.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from stock_research_core.api.schemas.common import ApiSchema
from stock_research_core.domain.operations.enums import BackgroundJobType


class IntegrationJobRequest(ApiSchema):
    job_type: BackgroundJobType
    parameters: dict[str, Any] = Field(default_factory=dict)


class IntegrationReadinessResponse(ApiSchema):
    """An integration-safe readiness summary - never a database URL, Redis
    URL, secret, internal traceback, or learner information."""

    ready: bool
    database_ready: bool
    redis_ready: bool
    migration_up_to_date: bool
