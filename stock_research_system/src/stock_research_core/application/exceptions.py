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


class InvalidAttemptStateError(StockResearchError):
    """An exercise attempt is not in a state that permits the requested operation
    (for example, submitting an answer for an attempt that is not STARTED)."""


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


class ResearchModelProviderError(StockResearchError):
    """The configured Live Research synthesis model provider could not
    produce an answer (spec G2D2/H1 correction pass, section 6).

    Deliberately a distinct exception from `TutorModelProviderError` -
    covers the same shape of failure (transient network error after
    bounded retries, non-2xx response, structured-output validation
    failure) but for the Ollama/OpenAI research-synthesis router, never
    conflated with the Tutor model path. Never carries the raw provider
    error message verbatim - always sanitized. The caller
    (`synthesize_research_response`) maps this to a bounded, localized
    `PROVIDER_FAILURE` response - never a fabricated answer.
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


class ObjectStorageError(StockResearchError):
    """Base exception for shared object-storage operations."""


class ObjectNotFoundError(ObjectStorageError):
    """No object exists at the requested key (and version, if given)."""


class ObjectStorageAccessDeniedError(ObjectStorageError):
    """The object-storage backend denied the requested operation."""


class ObjectStoragePrefixNotAllowedError(ObjectStorageError):
    """The requested key does not fall inside any configured allowed prefix."""


class SeedManifestValidationError(StockResearchError):
    """A seed-knowledge manifest (or one of its documents' front matter)
    failed structural, uniqueness, or path-safety validation."""


class SeedManifestDocumentNotFoundError(StockResearchError):
    """Single-document ingestion mode was requested for a document code
    that has no matching entry in the manifest."""


class SeedDocumentIntegrityError(StockResearchError):
    """A seed document's canonical bytes did not match the hash the caller
    expected - the manifest's `content_hash`, or the hash of what was
    just uploaded/downloaded to/from object storage."""


class ResearchRequestNotFoundError(StockResearchError):
    """No matching Live Research request was found."""


class ResearchRequestConflictError(StockResearchError):
    """The same requester + idempotency key was reused with a different
    request identity (normalized query, scope, or subject) than the one
    that produced the existing `ResearchRequest`."""


class ResearchRunNotFoundError(StockResearchError):
    """No matching Live Research run was found."""


class InvalidResearchRunStateError(StockResearchError):
    """The requested operation is not a legal transition for this
    `ResearchRun`'s current status."""


class EvidenceItemNotFoundError(StockResearchError):
    """No matching Live Research evidence item was found."""


class DuplicateEvidenceError(StockResearchError):
    """This run already has an evidence item with the same content_hash."""


class ResearchClaimNotFoundError(StockResearchError):
    """No matching Live Research claim was found."""


class ClaimEvidenceLinkNotFoundError(StockResearchError):
    """No matching claim-evidence link was found."""


class DuplicateClaimEvidenceLinkError(StockResearchError):
    """This claim/evidence pair is already linked with a stance."""


class InvalidClaimStatusTransitionError(StockResearchError):
    """The requested `ResearchClaim` status is not supported by the
    claim's current `ClaimEvidenceLink` rows (e.g. CORROBORATED requires a
    SUPPORTS link; UNRESOLVED_CONFLICT requires both a SUPPORTS and a
    CONTRADICTS link)."""


# -- Phase G2A1: Live Research provider adapters (Perplexity Search, SEC EDGAR) -----------------------------------------------


class LiveResearchProviderError(ProviderRequestError):
    """A Live Research provider (Perplexity Search, SEC EDGAR) request
    failed. Never carries the raw upstream response body, an API key, or
    an `Authorization` header - only a sanitized provider/endpoint/status
    description."""


class LiveResearchProviderTimeoutError(LiveResearchProviderError):
    """The provider request exceeded the configured transport timeout."""


class LiveResearchProviderRateLimitError(LiveResearchProviderError):
    """The provider responded HTTP 429.

    `retry_after_seconds` is populated only when the upstream
    `Retry-After` header was present and parsed as a safe, bounded
    non-negative integer; `None` otherwise. This exception never sleeps
    or retries on its own - that policy belongs to a later phase (G2B).
    """

    def __init__(self, message: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class LiveResearchProviderAccessError(LiveResearchProviderError):
    """The provider responded HTTP 401 or HTTP 403."""


class LiveResearchProviderResponseError(LiveResearchProviderError):
    """The provider responded with another 4xx/5xx status, or returned a
    structurally invalid or non-JSON body."""


class LiveResearchProviderConfigurationError(StockResearchError):
    """The Live Research provider settings are not usable as configured
    (missing required secret, non-HTTPS base URL, out-of-range numeric
    setting, ...). Never a provider *request* failure - raised while
    constructing settings/adapters, before any network call would be
    attempted."""


# -- Phase G2B: Live Research background-job orchestration -----------------------------------------------


class LiveResearchJobProviderNotConfiguredError(StockResearchError):
    """`LIVE_RESEARCH_RUN_EXECUTION` was invoked but a provider its scope
    requires was not available - either the top-level orchestration
    switch (`OperationsSettings.live_research_jobs_enabled`) is off, or
    the specific G2A1 provider (Perplexity Search / SEC EDGAR) is not
    enabled in its own settings. Raised before any provider call is
    attempted; never a provider *request* failure."""


class IntegrationClientNotFoundError(StockResearchError):
    """No matching integration client was found."""


class InvalidIntegrationClientIdentifierError(StockResearchError):
    """A CLI-supplied integration client id was not a valid UUID (Phase
    G2C Correction V2). The message is always a bounded, generic string -
    it never includes the rejected raw value, and the CLI never lets the
    underlying `ValueError`'s traceback reach the terminal."""


class IntegrationClientFinalJobTypeError(StockResearchError):
    """A revoke was requested that would remove an ACTIVE integration
    client's last remaining allowed job type. The client must either be
    disabled first, or granted a replacement job type before this one
    is revoked."""


class LiveResearchEvidenceNotAvailableError(StockResearchError):
    """The Live Research evidence endpoint was called for a job/run that
    is not a successfully completed Live Research run with recorded
    evidence. Always uses a bounded, generic message - never reveals
    the specific internal reason (wrong job type, non-terminal status,
    a malformed result_summary, or a ResearchRun that is not COMPLETED)."""


class LanguageServiceError(StockResearchError):
    """The shared `LanguageServicePort` could not translate a non-English
    question into a bounded English retrieval/search query (Phase G2E2A).

    Never raised by `detect_language()` or `localize()` - both are pure,
    local, and cannot fail. Only `translate_to_english_query()` raises
    this, covering a missing/misconfigured translation provider, a
    transient network failure after bounded retries, or a response that
    fails structured-output validation. Callers must degrade gracefully
    (e.g. `GroundedAITutorService` falls back to the original-language
    text as the retrieval query, which naturally yields an
    insufficient-evidence fallback against an English-only knowledge
    base) - never crash, never fabricate a translation."""


class LanguageServiceConfigurationError(StockResearchError):
    """`HEBREW_QUERY_BRIDGE_ENABLED=true` with `language_service_provider=
    'llm_backed'`, but no usable base URL/API key/model name could be
    resolved - neither from `LanguageServiceSettings`'s own optional
    overrides nor by reusing the configured `TutorModelSettings` (e.g.
    the Tutor itself is configured as `extractive`, which has no
    endpoint to reuse). Raised once, at composition time
    (`infrastructure.language.composition.build_language_service`),
    before any network call would be attempted - never a silent
    fallback to `UnavailableLanguageService` when the operator explicitly
    asked for translation to be enabled."""


class LiveResearchRequesterContextError(StockResearchError):
    """A `LIVE_RESEARCH_RUN_EXECUTION` job was requested or executed
    without exactly one trusted requester identity.

    Raised in two places, deliberately not one: the admin CLI's
    `--requested-by-account-id` XOR `--requested-by-integration-id`
    resolution (which also covers an unparsable UUID string, so the CLI
    prints a bounded error instead of a raw `ValueError` traceback), and
    `LiveResearchRunExecutionJobHandler` itself, which re-checks its
    `JobExecutionContext` because `SYSTEM`/`RETRY`-triggered and
    programmatic callers reach the registered job type without going
    through the CLI at all.

    Never derived from job parameters - `LiveResearchRunExecutionParameters`
    carries no requester field. Raised for missing or ambiguous
    (both/neither) identity, always before a `ResearchRequest` or
    `ResearchRun` exists; never retryable - the caller must supply
    exactly one and resubmit."""


# -- Phase G2D2: Coach-to-Live-Research resume -----------------------------------------------


class CoachResearchResumeStateConflictError(StockResearchError):
    """`COACH_RESEARCH_RESUME` was invoked for a Coach run whose stored
    `run_id`/`thread_id`/`research_job_id` does not match the resume
    job's own parameters, or whose status is not `WAITING_FOR_RESEARCH`
    and does not match the "already resumed" idempotent-no-op shape
    either. Always a hard failure - never silently ignored, since it
    means the resume job and the run it targets have drifted out of
    sync."""


class CoachResearchResumeOwnershipError(StockResearchError):
    """The `LIVE_RESEARCH_RUN_EXECUTION` job's `requested_by_account_id`
    (or the `ResearchRequest`'s own requester) does not match the Coach
    run's `trusted_account_id`. Never retryable - a cross-account
    mismatch can never resolve itself."""


class CoachResearchResumeInconsistentJobError(StockResearchError):
    """The linked `BackgroundJob` was not `LIVE_RESEARCH_RUN_EXECUTION`,
    was not terminal, or its terminal interpretation (spec section 15)
    was `INCONSISTENT`. Fails closed - never resumes the graph with an
    ungrounded or ambiguous outcome."""


class CoachResearchResumeNotConfiguredError(StockResearchError):
    """`COACH_RESEARCH_RESUME` was routed to a process that was not
    composed with a `PersonalizedLearningOrchestratorService` (every
    process except `finquest-worker-coach`, which alone consumes the
    `finquest.coach` queue). Reaching this handler on any other process
    is a routing bug, not a normal operating condition."""
