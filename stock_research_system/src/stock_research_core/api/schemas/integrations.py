"""Request/response DTOs for `/api/v1/integrations/n8n`.

`IntegrationJobRequest.parameters` is a plain JSON object at the schema
layer, but is never accepted as "unvalidated arbitrary JSON" - it is
always parsed against the job type's registered parameter model
(`application.operations.job_registry`) before a job is created, exactly
like the admin `CreateJobRequest`. No integration credential (key ID,
raw key, or key hash) is ever included in a response schema.

`EvidenceItemSummary`/`EvidencePageResponse` (Phase G2C) are a
deliberately bounded, provenance-safe view of `EvidenceItem`: they never
carry `raw_excerpt`, `normalized_text`, `structured_facts`, or any
provider metadata - only enough to let an n8n workflow report what kind
of evidence was found and where it came from. `EvidenceClassification`
and `SourceType` are exposed literally (never renamed or upgraded to
imply a stronger provenance guarantee than the data actually has).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from stock_research_core.api.schemas.common import ApiSchema
from stock_research_core.domain.live_research.enums import EvidenceClassification, SourceType
from stock_research_core.domain.live_research.models import EvidenceItem
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


class EvidenceItemSummary(ApiSchema):
    """A bounded, provenance-safe view of one `EvidenceItem`. Excludes
    `raw_excerpt`, `normalized_text`, `structured_facts`, and any
    provider metadata - never a raw provider response."""

    evidence_id: UUID
    source_type: SourceType
    classification: EvidenceClassification
    source_title: str
    publisher: str
    source_url: str | None = None
    official_identifier: str | None = None
    published_at: datetime | None = None

    @classmethod
    def from_domain(cls, item: EvidenceItem) -> "EvidenceItemSummary":
        return cls(
            evidence_id=item.evidence_id,
            source_type=item.source_type,
            classification=item.classification,
            source_title=item.source_title,
            publisher=item.publisher,
            source_url=str(item.source_url) if item.source_url else None,
            official_identifier=item.official_identifier,
            published_at=item.published_at,
        )


class EvidencePageResponse(ApiSchema):
    """A single database-paginated page of `EvidenceItemSummary` rows for
    one completed `ResearchRun`. `has_more` is `True` only when the
    repository returned an extra (`limit + 1`-th) row - the router never
    issues an unbounded query or a separate `COUNT(*)`."""

    items: list[EvidenceItemSummary]
    limit: int = Field(ge=1, le=50)
    offset: int = Field(ge=0)
    has_more: bool
    next_offset: int | None = None
