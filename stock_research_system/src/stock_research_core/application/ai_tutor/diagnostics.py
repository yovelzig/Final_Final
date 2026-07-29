"""Bounded, allow-listed diagnostic logging for the AI Tutor pipeline
(spec G2D2 section 2).

`log_tutor_diagnostic()` is the only sanctioned way tutor-pipeline code
logs a model-quality signal - it accepts a fixed, explicit set of
keyword-only fields (provider identity, bounded counts, status/issue
enums, correlation ids, timing) and nothing else. There is no free-text
field on this function, so a call site can never pass a raw question,
model answer, retrieved chunk content, or credential through it -
unlike a generic `logger.info(**kwargs)` call, which could.
"""

from __future__ import annotations

from uuid import UUID

from stock_research_core.domain.ai_tutor.enums import GroundingStatus, TutorProviderType
from stock_research_core.infrastructure.operations.structured_logging import get_logger

_logger = get_logger("stock_research_core.ai_tutor.diagnostics")


class TutorDiagnosticIssueCode:
    """Bounded set of tutor-pipeline diagnostic issue codes (spec G2D2
    section 2). Plain string constants, not a `StrEnum`, so a code can be
    used directly as a member of `RuleBasedTutorGuardrail.validate_output`'s
    existing `issues: list[str]` return value without a conversion step."""

    RETRIEVAL_INSUFFICIENT = "RETRIEVAL_INSUFFICIENT"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    MALFORMED_MODEL_RESPONSE = "MALFORMED_MODEL_RESPONSE"
    MISSING_CITATIONS = "MISSING_CITATIONS"
    INVALID_CITATION_CHUNK_ID = "INVALID_CITATION_CHUNK_ID"
    UNVERIFIED_URL = "UNVERIFIED_URL"
    UNSAFE_GENERATED_OUTPUT = "UNSAFE_GENERATED_OUTPUT"
    OUTPUT_SCHEMA_VIOLATION = "OUTPUT_SCHEMA_VIOLATION"
    REPAIR_ATTEMPT_FAILED = "REPAIR_ATTEMPT_FAILED"

    ALL = frozenset(
        {
            RETRIEVAL_INSUFFICIENT, MODEL_TIMEOUT, PROVIDER_ERROR, MALFORMED_MODEL_RESPONSE, MISSING_CITATIONS,
            INVALID_CITATION_CHUNK_ID, UNVERIFIED_URL, UNSAFE_GENERATED_OUTPUT, OUTPUT_SCHEMA_VIOLATION,
            REPAIR_ATTEMPT_FAILED,
        }
    )


def log_tutor_diagnostic(
    *,
    provider_type: TutorProviderType,
    model_name: str,
    attempt_number: int,
    retrieval_candidate_count: int,
    cited_id_count: int,
    grounding_status: GroundingStatus | None = None,
    issue_codes: list[str] | None = None,
    conversation_id: UUID | None = None,
    coach_correlation_id: UUID | None = None,
    elapsed_ms: float | None = None,
) -> None:
    """Every keyword here is a bounded identifier, count, or enum value -
    never prompt text, model output, or chunk content. `issue_codes`
    entries must be members of `TutorDiagnosticIssueCode.ALL`; unknown
    codes are dropped rather than logged verbatim, so an unexpected
    upstream string can never smuggle unbounded text into the log."""
    bounded_issue_codes = [code for code in (issue_codes or []) if code in TutorDiagnosticIssueCode.ALL]
    _logger.info(
        "tutor_diagnostic",
        provider_type=provider_type.value,
        model_name=model_name,
        attempt_number=attempt_number,
        retrieval_candidate_count=retrieval_candidate_count,
        cited_id_count=cited_id_count,
        grounding_status=grounding_status.value if grounding_status is not None else None,
        issue_codes=bounded_issue_codes,
        conversation_id=str(conversation_id) if conversation_id is not None else None,
        coach_correlation_id=str(coach_correlation_id) if coach_correlation_id is not None else None,
        elapsed_ms=elapsed_ms,
    )
