"""Application-level exceptions.

These describe expected, controlled failure modes of the application
layer (security resolution and market-data ingestion so far). Callers
such as the CLI are expected to catch `StockResearchError` and print a
clean message instead of a raw provider stack trace.
"""

from __future__ import annotations

from stock_research_core.domain.virtual_portfolio.enums import TradeRejectionReason


class StockResearchError(Exception):
    """Base exception for the system."""


class InvalidSecurityQueryError(StockResearchError):
    """Neither a usable ticker nor company name was supplied."""


class SecurityNotFoundError(StockResearchError):
    """No matching tradable security was found."""


class AmbiguousSecurityError(StockResearchError):
    """Several plausible securities were found."""


class MarketDataUnavailableError(StockResearchError):
    """The provider returned no usable market data."""


class InvalidMarketDataError(StockResearchError):
    """The provider returned structurally invalid market data."""


class UnsupportedIntervalError(StockResearchError):
    """The requested interval is not supported in the current MVP."""


class ProviderRequestError(StockResearchError):
    """The external market-data provider request failed."""


class SecurityNotStoredError(StockResearchError):
    """Incremental ingestion was requested for a ticker with no stored Security.

    The caller must perform historical ingestion first so a stored
    Security (and at least one stored bar) exists to increment from.
    """


class NoStoredMarketDataError(StockResearchError):
    """Incremental ingestion was requested but no stored bar exists yet.

    There is no `last_stored_bar_at` to increment from, and this method
    has no `start_at` parameter to fall back to historical ingestion.
    The caller must perform historical ingestion first.
    """


class PersistenceError(StockResearchError):
    """A database operation failed while persisting ingestion results."""


class DatabaseMappingError(StockResearchError):
    """A stored database row could not be mapped to a valid domain object."""


class LearnerNotFoundError(StockResearchError):
    """No matching learner profile was found."""


class LearningPathNotFoundError(StockResearchError):
    """No matching learning path was found."""


class LearningModuleNotFoundError(StockResearchError):
    """No matching learning module was found."""


class LessonNotFoundError(StockResearchError):
    """No matching lesson was found."""


class ExerciseNotFoundError(StockResearchError):
    """No matching exercise was found."""


class ExerciseAttemptNotFoundError(StockResearchError):
    """No matching exercise attempt was found."""


class InvalidGradingRequestError(StockResearchError):
    """The submitted answer or exercise configuration cannot be graded as given."""


class InactiveLearnerError(StockResearchError):
    """An adaptive-learning operation was requested for an inactive learner."""


class LearningSessionNotFoundError(StockResearchError):
    """No matching learning session was found."""


class AdaptiveDecisionNotFoundError(StockResearchError):
    """No matching adaptive decision was found."""


class InvalidDecisionStateError(StockResearchError):
    """The adaptive decision is not in a state that allows the requested action."""


class DiagnosticAssessmentNotFoundError(StockResearchError):
    """No matching diagnostic assessment was found."""


class DiagnosticAssessmentItemNotFoundError(StockResearchError):
    """No matching diagnostic assessment item was found."""


class MarketScenarioNotFoundError(StockResearchError):
    """No matching historical market scenario was found."""


class ScenarioSubmissionNotFoundError(StockResearchError):
    """No matching scenario submission was found."""


class ScenarioOutcomeNotFoundError(StockResearchError):
    """No matching scenario outcome was found."""


class InvalidScenarioStateError(StockResearchError):
    """The scenario or submission is not in a state that allows the requested action."""


class ScenarioValidationError(StockResearchError):
    """A scenario failed administrative validation and cannot be marked READY/PUBLISHED."""


class InsufficientScenarioDataError(StockResearchError):
    """Not enough stored market bars exist to compute a scenario calculation."""


class VirtualPortfolioNotFoundError(StockResearchError):
    """No matching virtual portfolio was found."""


class PortfolioTransactionNotFoundError(StockResearchError):
    """No matching portfolio transaction was found."""


class PortfolioValuationRunNotFoundError(StockResearchError):
    """No matching portfolio valuation run was found."""


class InvalidPortfolioStateError(StockResearchError):
    """The portfolio is not in a state that allows the requested action."""


class TradeRejectedError(StockResearchError):
    """A previewed or executed trade was controllably rejected.

    Carries the same `TradeRejectionReason` and sanitized English
    message that would be stored on a REJECTED `PortfolioTransaction`,
    so callers (CLI, service) can present a clean message instead of a
    stack trace.
    """

    def __init__(self, reason: TradeRejectionReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


class PortfolioValuationError(StockResearchError):
    """A portfolio valuation could not be computed (e.g. no priced holdings)."""


class InsufficientPortfolioValuationDataError(StockResearchError):
    """Fewer than two stored valuation snapshots fall within the requested
    window, so a performance summary (which needs a start and an end
    point) cannot be computed. Never a raw `ValueError` - callers (API,
    CLI) can rely on this being a `StockResearchError` and present a
    clean, actionable message instead of a stack trace."""


class EmbeddingProviderError(StockResearchError):
    """The configured embedding provider could not embed the requested text.

    Covers a missing optional dependency (e.g. `sentence-transformers`
    not installed), a model-loading failure, or a returned vector whose
    dimension does not match the configured `EMBEDDING_DIMENSION`.
    """


class TutorModelProviderError(StockResearchError):
    """The configured tutor-model provider could not produce an answer.

    Covers transient network failures (after bounded retries), a
    non-2xx response, and a response that fails structured-output
    validation after one correction attempt. Never carries the raw
    provider error message verbatim - always sanitized.
    """


class UnsupportedDocumentError(StockResearchError):
    """A local document could not be parsed (unsupported type, oversized, or scanned/image-only)."""


class TutorConversationNotFoundError(StockResearchError):
    """No matching tutor conversation was found."""


class TutorConversationNotActiveError(StockResearchError):
    """A tutor operation was requested against a conversation that is not ACTIVE."""


class KnowledgeSourceNotFoundError(StockResearchError):
    """No matching knowledge source was found."""


class KnowledgeDocumentNotFoundError(StockResearchError):
    """No matching knowledge document was found."""


class AuthenticationFailedError(StockResearchError):
    """Login failed. Always uses a generic message - never reveals whether the email exists."""


class AccountLockedError(StockResearchError):
    """The account is temporarily LOCKED after too many failed login attempts."""


class AccountDisabledError(StockResearchError):
    """The account is DISABLED and cannot authenticate."""


class DuplicateAccountError(StockResearchError):
    """An account with this normalized email (or linked learner) already exists."""


class AccountNotFoundError(StockResearchError):
    """No matching user account was found (administrative lookup only - login
    failures always use the generic `AuthenticationFailedError` instead, so this
    is never reachable from an unauthenticated caller)."""


class InvalidPasswordError(StockResearchError):
    """The supplied password fails the FinQuest password policy. Never carries the password itself."""


class InvalidRefreshTokenError(StockResearchError):
    """The supplied refresh token is missing, expired, already used, or otherwise invalid.

    Covers rotated-token reuse (which additionally revokes the whole
    token family as a side effect, per spec ss11).
    """


class InvalidAccessTokenError(StockResearchError):
    """The supplied access token failed structural, signature, issuer, audience, or expiry validation."""


class InsufficientPermissionError(StockResearchError):
    """The authenticated principal's role/ownership does not permit this action."""


class RateLimitExceededError(StockResearchError):
    """The caller exceeded a configured rate limit for this action."""


# -- Phase 11: background jobs, distributed locking, and n8n integration -----------------------------------------------


class TransientInfrastructureError(StockResearchError):
    """A background-job dependency (queue delivery, distributed lock,
    connection pool) failed in a way expected to be transient. Distinct
    from provider-specific errors so retry policies can classify
    infrastructure failures independently of e.g. market-data-provider
    failures."""


class BackgroundJobNotFoundError(StockResearchError):
    """No matching background job was found."""


class InvalidJobStateError(StockResearchError):
    """The job is not in a state that allows the requested action
    (e.g. cancelling an already-terminal job, requeuing a job that has
    exhausted its maximum attempts)."""


class InvalidJobParametersError(StockResearchError):
    """The submitted job parameters failed validation against the
    job type's registered parameter model."""


class JobTypeNotAllowedError(StockResearchError):
    """The requested job type is not permitted for this trigger source or
    this integration client's allow-list."""


class LockAcquisitionError(StockResearchError):
    """A distributed resource lock could not be acquired within the
    bounded wait window - another job is already operating on the same
    resource."""


class IntegrationAuthenticationFailedError(StockResearchError):
    """n8n / integration-client API-key authentication failed. Always uses
    a generic message - never reveals whether the key ID exists."""


class IntegrationRequestConflictError(StockResearchError):
    """The same `external_request_id` was replayed with a different
    request body than the one that produced the canonical job."""


class LearningOrchestratorThreadNotFoundError(StockResearchError):
    """No matching learning-coach thread was found for this learner."""


class LearningOrchestratorThreadClosedError(StockResearchError):
    """A closed thread cannot receive a new run."""


class LearningOrchestratorRunNotFoundError(StockResearchError):
    """No matching learning-coach run was found for this learner."""


class LearningOrchestratorRunNotWaitingError(StockResearchError):
    """A resume/approval was submitted for a run that is not currently
    `WAITING_FOR_LEARNER`."""


class LearningOrchestratorRunNotCancellableError(StockResearchError):
    """A cancel was requested for a run already in a terminal state."""


class LearningActionProposalNotFoundError(StockResearchError):
    """No matching action proposal was found for this run."""


class LearningActionProposalAlreadyDecidedError(StockResearchError):
    """A different approval decision was already recorded for this
    proposal - re-submitting a differing decision is a 409, not an
    idempotent no-op."""


class LearningActionProposalExpiredError(StockResearchError):
    """The proposal's approval window has expired."""


class QualityEvaluationSuiteNotFoundError(StockResearchError):
    """No matching quality-evaluation suite was found."""


class QualityEvaluationSuiteNotApprovedError(StockResearchError):
    """A production/release-gate evaluation run was requested against a
    suite that is not currently APPROVED."""


class QualityEvaluationCaseNotFoundError(StockResearchError):
    """No matching quality-evaluation case was found."""


class QualityEvaluationRunNotFoundError(StockResearchError):
    """No matching quality-evaluation run was found."""


class QualityEvaluationBaselineNotFoundError(StockResearchError):
    """No matching quality-evaluation baseline was found."""


class QualityEvaluationBaselineNotComparableError(StockResearchError):
    """A baseline comparison was requested between two runs that are not
    directly comparable (different suite versions, missing metrics)."""
