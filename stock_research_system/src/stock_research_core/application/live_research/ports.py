"""Application-level repository Protocols for the Live Research domain
(Phase G1).

Pure `Protocol` definitions - no SQLAlchemy (or any other infrastructure
library) is imported here. Concrete implementations live under
`stock_research_core.infrastructure.database`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from stock_research_core.application.live_research.synthesis_models import (
    ResearchSynthesisRequest,
    ResearchSynthesisResult,
)
from stock_research_core.domain.live_research.enums import ClaimStatus, EvidenceStance, FailureCategory
from stock_research_core.domain.live_research.models import (
    ClaimEvidenceLink,
    EvidenceItem,
    ResearchClaim,
    ResearchRequest,
    ResearchRun,
)


class ResearchRequestRepositoryPort(Protocol):
    """Persists and queries `ResearchRequest` objects."""

    async def create(self, request: ResearchRequest) -> ResearchRequest: ...

    async def get(self, request_id: UUID) -> ResearchRequest | None: ...

    async def get_for_update(self, request_id: UUID) -> ResearchRequest | None: ...

    async def get_by_idempotency_key(
        self, *, requester_key: str, idempotency_key: str
    ) -> ResearchRequest | None: ...


class ResearchRunRepositoryPort(Protocol):
    """Persists and queries `ResearchRun` objects."""

    async def create(self, run: ResearchRun) -> ResearchRun: ...

    async def get(self, run_id: UUID, *, for_update: bool = False) -> ResearchRun | None: ...

    async def get_active_run_for_request(self, request_id: UUID) -> ResearchRun | None:
        """The request's single non-terminal run, if one exists."""
        ...

    async def get_max_attempt_number(self, request_id: UUID) -> int:
        """The highest `attempt_number` recorded for this request, or 0
        if no run yet exists - so the next attempt is always `+ 1`."""
        ...

    async def list_for_request(self, request_id: UUID) -> list[ResearchRun]: ...

    async def mark_running(self, run_id: UUID, *, started_at: datetime) -> ResearchRun: ...

    async def mark_completed(self, run_id: UUID, *, completed_at: datetime) -> ResearchRun: ...

    async def mark_failed(
        self,
        run_id: UUID,
        *,
        completed_at: datetime,
        failure_category: FailureCategory,
        failure_message: str,
        retryable: bool,
    ) -> ResearchRun: ...

    async def mark_cancelled(self, run_id: UUID, *, cancelled_at: datetime) -> ResearchRun: ...


class EvidenceItemRepositoryPort(Protocol):
    """Persists and queries immutable `EvidenceItem` records."""

    async def create(self, item: EvidenceItem) -> EvidenceItem: ...

    async def get(self, evidence_id: UUID) -> EvidenceItem | None: ...

    async def get_by_content_hash(self, run_id: UUID, content_hash: str) -> EvidenceItem | None: ...

    async def list_for_run(self, run_id: UUID) -> list[EvidenceItem]: ...

    async def list_page_for_run(self, run_id: UUID, *, limit: int, offset: int) -> list[EvidenceItem]:
        """A single deterministically-ordered page (Phase G2C), applying
        `LIMIT`/`OFFSET` in SQL rather than loading every row and
        slicing in Python. Ordering matches `list_for_run`'s existing
        `retrieved_at` ascending order, with `evidence_id` as a stable
        tiebreaker so pagination never skips or repeats a row when two
        items share the same `retrieved_at` timestamp."""
        ...


class ResearchClaimRepositoryPort(Protocol):
    """Persists and queries only `ResearchClaim`'s own scalar fields.
    Never returns or accepts evidence-ID lists - see
    `ClaimEvidenceLinkRepositoryPort` for the claim<->evidence relationship."""

    async def create(self, claim: ResearchClaim) -> ResearchClaim: ...

    async def get(self, claim_id: UUID) -> ResearchClaim | None: ...

    async def list_for_run(self, run_id: UUID) -> list[ResearchClaim]: ...

    async def update_status(
        self, claim_id: UUID, status: ClaimStatus, *, confidence_score: float | None = None
    ) -> ResearchClaim: ...


class ResearchModelPort(Protocol):
    """Generates a grounded research synthesis answer from a fully-built
    `ResearchSynthesisRequest` (spec G2D2/H1 correction pass, section 6).
    Deliberately a distinct Protocol from `ai_tutor.ports.TutorModelPort`
    - never interchangeable, even though a concrete adapter may call the
    same underlying Ollama/OpenAI endpoint."""

    async def generate(self, request: ResearchSynthesisRequest) -> ResearchSynthesisResult: ...


class ClaimEvidenceLinkRepositoryPort(Protocol):
    """The sole persistence surface for the claim<->evidence relationship.
    No other port exposes evidence-ID lists."""

    async def create_link(
        self, claim_id: UUID, evidence_id: UUID, stance: EvidenceStance
    ) -> ClaimEvidenceLink: ...

    async def get_link(self, claim_id: UUID, evidence_id: UUID) -> ClaimEvidenceLink | None: ...

    async def list_links_for_claim(self, claim_id: UUID) -> list[ClaimEvidenceLink]: ...

    async def list_links_for_evidence(self, evidence_id: UUID) -> list[ClaimEvidenceLink]: ...
