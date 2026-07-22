"""Grounded AI tutor and knowledge-base use cases: result models,
repository/provider ports, the deterministic chunker, guardrail policy,
and prompt builder.

`GroundedAITutorService` (and the lesson/scenario/portfolio tutor
services built on it) are intentionally not re-exported here: they
import `stock_research_core.application.persistence.ports` (for
`UnitOfWorkPort`), which in turn imports
`stock_research_core.application.ai_tutor.ports` - eagerly importing
any tutor service from this package's `__init__.py` would make that a
circular import, the same issue already solved for
`application.virtual_portfolio` and other feature packages. Import them
directly, e.g.
`from stock_research_core.application.ai_tutor.service import GroundedAITutorService`.
"""

from stock_research_core.application.ai_tutor.chunking import CHUNKING_VERSION, HeadingAwareWordChunker
from stock_research_core.application.ai_tutor.guardrails import GUARDRAIL_POLICY_VERSION, RuleBasedTutorGuardrail
from stock_research_core.application.ai_tutor.models import (
    KnowledgeIngestionRunRecord,
    KnowledgeIngestionSummary,
    LearnerSafeCitation,
    RetrievalCandidate,
    RetrievalEvaluationResult,
    TutorContext,
    TutorModelRequest,
    TutorModelResult,
    TutorResponse,
)
from stock_research_core.application.ai_tutor.prompt_builder import PROMPT_VERSION, GroundedTutorPromptBuilder

__all__ = [
    "CHUNKING_VERSION",
    "GUARDRAIL_POLICY_VERSION",
    "PROMPT_VERSION",
    "GroundedTutorPromptBuilder",
    "HeadingAwareWordChunker",
    "KnowledgeIngestionRunRecord",
    "KnowledgeIngestionSummary",
    "LearnerSafeCitation",
    "RetrievalCandidate",
    "RetrievalEvaluationResult",
    "RuleBasedTutorGuardrail",
    "TutorContext",
    "TutorModelRequest",
    "TutorModelResult",
    "TutorResponse",
]
