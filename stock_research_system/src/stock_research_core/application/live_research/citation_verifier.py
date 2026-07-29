"""`ResearchEvidenceCitationVerifier` (spec G2D2 section 17): confirms
every cited `EvidenceItem` ID actually belongs to the verified
`ResearchRun` before it is ever used in a learner-facing answer - never
trusts a model-supplied (or otherwise caller-supplied) evidence ID at
face value.

Deliberately a distinct class from `ai_tutor.citation_verifier.
TutorCitationVerifier` - Tutor citations are Tutor knowledge-chunk IDs
from `KnowledgeRetrieverPort` candidates; Live Research citations are
`EvidenceItem` IDs from a verified `ResearchRun`. The two must never be
interchangeable, and a Tutor chunk ID must never be accepted here (or
vice versa).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from stock_research_core.domain.live_research.enums import EvidenceClassification
from stock_research_core.domain.live_research.models import EvidenceItem


@dataclass(frozen=True)
class ResearchCitationVerificationResult:
    #: IDs that were cited and do belong to `research_run_id`.
    verified_evidence_ids: list[UUID]
    #: IDs that were cited but do not belong to `research_run_id` -
    #: either fabricated outright or (accidentally or maliciously)
    #: pulled from a different run. Always rejected, never partially
    #: trusted.
    rejected_evidence_ids: list[UUID]

    @property
    def all_verified(self) -> bool:
        return not self.rejected_evidence_ids


class ResearchEvidenceCitationVerifier:
    def verify(
        self, *, cited_evidence_ids: list[UUID], verified_run_evidence: list[EvidenceItem], research_run_id: UUID,
    ) -> ResearchCitationVerificationResult:
        """`verified_run_evidence` must already be a fresh, trusted
        PostgreSQL read for exactly this `research_run_id` (never a
        resume-payload value) - this method only checks that every
        citation is a member of that set and belongs to the run it
        claims to. An `EvidenceItem` whose own `run_id` does not match
        `research_run_id` (should never happen given a correct caller,
        but checked explicitly rather than assumed) is treated as if it
        were not in the set at all."""
        valid_ids = {item.evidence_id for item in verified_run_evidence if item.run_id == research_run_id}
        verified = [evidence_id for evidence_id in cited_evidence_ids if evidence_id in valid_ids]
        rejected = [evidence_id for evidence_id in cited_evidence_ids if evidence_id not in valid_ids]
        return ResearchCitationVerificationResult(verified_evidence_ids=verified, rejected_evidence_ids=rejected)

    def split_by_official_classification(
        self, evidence_items: list[EvidenceItem]
    ) -> tuple[list[EvidenceItem], list[EvidenceItem]]:
        """Keeps official and non-official evidence explicitly
        distinguishable (spec section 17) - returns `(official,
        non_official)`, never merged into one undifferentiated list."""
        official = [item for item in evidence_items if item.classification == EvidenceClassification.OFFICIAL]
        non_official = [item for item in evidence_items if item.classification != EvidenceClassification.OFFICIAL]
        return official, non_official
