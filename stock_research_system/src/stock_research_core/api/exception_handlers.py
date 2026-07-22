"""Maps application exceptions (and FastAPI's own validation/HTTP
exceptions) to the FinQuest API's consistent error envelope.

Never exposes SQL, stack traces, file paths, provider authorization
data, database URLs, or raw internal exception representations - every
message here is either a pre-written safe English string already
attached to a `StockResearchError` subclass, or a fixed generic
message for unexpected failures.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from stock_research_core.api.schemas.common import ApiError, ApiErrorBody, ApiErrorDetail
from stock_research_core.application.quality_evaluation.datasets import DatasetValidationError
from stock_research_core.application.exceptions import (
    AccountDisabledError,
    AccountLockedError,
    AccountNotFoundError,
    AdaptiveDecisionNotFoundError,
    AmbiguousSecurityError,
    AuthenticationFailedError,
    BackgroundJobNotFoundError,
    DatabaseMappingError,
    DiagnosticAssessmentItemNotFoundError,
    DiagnosticAssessmentNotFoundError,
    DuplicateAccountError,
    EmbeddingProviderError,
    ExerciseAttemptNotFoundError,
    ExerciseNotFoundError,
    InactiveLearnerError,
    InsufficientPermissionError,
    InsufficientPortfolioValuationDataError,
    InsufficientScenarioDataError,
    IntegrationAuthenticationFailedError,
    IntegrationRequestConflictError,
    InvalidAccessTokenError,
    InvalidDecisionStateError,
    InvalidGradingRequestError,
    InvalidJobParametersError,
    InvalidJobStateError,
    InvalidMarketDataError,
    InvalidPasswordError,
    InvalidPortfolioStateError,
    InvalidRefreshTokenError,
    InvalidScenarioStateError,
    InvalidSecurityQueryError,
    JobTypeNotAllowedError,
    KnowledgeDocumentNotFoundError,
    KnowledgeSourceNotFoundError,
    LearnerNotFoundError,
    LearningActionProposalAlreadyDecidedError,
    LearningActionProposalExpiredError,
    LearningActionProposalNotFoundError,
    LearningModuleNotFoundError,
    LearningOrchestratorRunNotCancellableError,
    LearningOrchestratorRunNotFoundError,
    LearningOrchestratorRunNotWaitingError,
    LearningOrchestratorThreadClosedError,
    LearningOrchestratorThreadNotFoundError,
    LearningPathNotFoundError,
    LearningSessionNotFoundError,
    LessonNotFoundError,
    LockAcquisitionError,
    MarketDataUnavailableError,
    MarketScenarioNotFoundError,
    NoStoredMarketDataError,
    PersistenceError,
    PortfolioTransactionNotFoundError,
    PortfolioValuationError,
    PortfolioValuationRunNotFoundError,
    ProviderRequestError,
    RateLimitExceededError,
    ScenarioOutcomeNotFoundError,
    ScenarioSubmissionNotFoundError,
    ScenarioValidationError,
    SecurityNotFoundError,
    SecurityNotStoredError,
    StockResearchError,
    QualityEvaluationBaselineNotComparableError,
    QualityEvaluationBaselineNotFoundError,
    QualityEvaluationCaseNotFoundError,
    QualityEvaluationRunNotFoundError,
    QualityEvaluationSuiteNotApprovedError,
    QualityEvaluationSuiteNotFoundError,
    TradeRejectedError,
    TransientInfrastructureError,
    TutorConversationNotActiveError,
    TutorConversationNotFoundError,
    TutorModelProviderError,
    UnsupportedDocumentError,
    UnsupportedIntervalError,
    VirtualPortfolioNotFoundError,
)

logger = logging.getLogger("stock_research_core.api")

# Suggested mapping (spec ss18), extended to cover every existing
# `StockResearchError` subclass so no application exception ever falls
# through to an opaque 500 by accident.
_EXCEPTION_STATUS_MAP: dict[type[Exception], tuple[int, str]] = {
    # Identity / authentication / authorization
    AuthenticationFailedError: (401, "AUTHENTICATION_FAILED"),
    AccountNotFoundError: (404, "NOT_FOUND"),
    AccountLockedError: (401, "ACCOUNT_LOCKED"),
    AccountDisabledError: (401, "ACCOUNT_DISABLED"),
    InvalidAccessTokenError: (401, "INVALID_ACCESS_TOKEN"),
    InvalidRefreshTokenError: (401, "INVALID_REFRESH_TOKEN"),
    InsufficientPermissionError: (403, "INSUFFICIENT_PERMISSION"),
    InactiveLearnerError: (403, "INACTIVE_LEARNER"),
    DuplicateAccountError: (409, "DUPLICATE_ACCOUNT"),
    InvalidPasswordError: (422, "INVALID_PASSWORD"),
    DatasetValidationError: (422, "INVALID_DATASET"),
    RateLimitExceededError: (429, "RATE_LIMIT_EXCEEDED"),
    # Not found -> 404 (an owned-but-missing resource uses the same code,
    # so a non-owner learner cannot distinguish "missing" from "not yours")
    SecurityNotFoundError: (404, "NOT_FOUND"),
    LearnerNotFoundError: (404, "NOT_FOUND"),
    LearningPathNotFoundError: (404, "NOT_FOUND"),
    LearningModuleNotFoundError: (404, "NOT_FOUND"),
    LessonNotFoundError: (404, "NOT_FOUND"),
    ExerciseNotFoundError: (404, "NOT_FOUND"),
    ExerciseAttemptNotFoundError: (404, "NOT_FOUND"),
    LearningSessionNotFoundError: (404, "NOT_FOUND"),
    AdaptiveDecisionNotFoundError: (404, "NOT_FOUND"),
    DiagnosticAssessmentNotFoundError: (404, "NOT_FOUND"),
    DiagnosticAssessmentItemNotFoundError: (404, "NOT_FOUND"),
    MarketScenarioNotFoundError: (404, "NOT_FOUND"),
    ScenarioSubmissionNotFoundError: (404, "NOT_FOUND"),
    ScenarioOutcomeNotFoundError: (404, "NOT_FOUND"),
    VirtualPortfolioNotFoundError: (404, "NOT_FOUND"),
    PortfolioTransactionNotFoundError: (404, "NOT_FOUND"),
    PortfolioValuationRunNotFoundError: (404, "NOT_FOUND"),
    TutorConversationNotFoundError: (404, "NOT_FOUND"),
    KnowledgeSourceNotFoundError: (404, "NOT_FOUND"),
    KnowledgeDocumentNotFoundError: (404, "NOT_FOUND"),
    BackgroundJobNotFoundError: (404, "NOT_FOUND"),
    LearningOrchestratorThreadNotFoundError: (404, "NOT_FOUND"),
    LearningOrchestratorRunNotFoundError: (404, "NOT_FOUND"),
    LearningActionProposalNotFoundError: (404, "NOT_FOUND"),
    QualityEvaluationSuiteNotFoundError: (404, "NOT_FOUND"),
    QualityEvaluationCaseNotFoundError: (404, "NOT_FOUND"),
    QualityEvaluationRunNotFoundError: (404, "NOT_FOUND"),
    QualityEvaluationBaselineNotFoundError: (404, "NOT_FOUND"),
    QualityEvaluationSuiteNotApprovedError: (409, "SUITE_NOT_APPROVED"),
    QualityEvaluationBaselineNotComparableError: (409, "BASELINE_NOT_COMPARABLE"),
    # Conflict / invalid state -> 409
    InvalidDecisionStateError: (409, "INVALID_STATE"),
    InvalidScenarioStateError: (409, "INVALID_STATE"),
    InvalidPortfolioStateError: (409, "INVALID_STATE"),
    TutorConversationNotActiveError: (409, "INVALID_STATE"),
    TradeRejectedError: (409, "TRADE_REJECTED"),
    AmbiguousSecurityError: (409, "AMBIGUOUS_SECURITY"),
    SecurityNotStoredError: (409, "SECURITY_NOT_STORED"),
    NoStoredMarketDataError: (409, "NO_STORED_DATA"),
    InvalidJobStateError: (409, "INVALID_STATE"),
    IntegrationRequestConflictError: (409, "REQUEST_CONFLICT"),
    LearningOrchestratorThreadClosedError: (409, "THREAD_CLOSED"),
    LearningOrchestratorRunNotWaitingError: (409, "RUN_NOT_WAITING"),
    LearningOrchestratorRunNotCancellableError: (409, "RUN_NOT_CANCELLABLE"),
    LearningActionProposalAlreadyDecidedError: (409, "PROPOSAL_ALREADY_DECIDED"),
    LearningActionProposalExpiredError: (409, "PROPOSAL_EXPIRED"),
    # Validation-ish -> 422
    InvalidGradingRequestError: (422, "VALIDATION_ERROR"),
    InvalidSecurityQueryError: (422, "VALIDATION_ERROR"),
    UnsupportedIntervalError: (422, "VALIDATION_ERROR"),
    UnsupportedDocumentError: (422, "UNSUPPORTED_DOCUMENT"),
    ScenarioValidationError: (422, "VALIDATION_ERROR"),
    InsufficientScenarioDataError: (422, "INSUFFICIENT_DATA"),
    PortfolioValuationError: (422, "PORTFOLIO_VALUATION_ERROR"),
    InsufficientPortfolioValuationDataError: (422, "INSUFFICIENT_PORTFOLIO_VALUATION_DATA"),
    InvalidJobParametersError: (422, "VALIDATION_ERROR"),
    JobTypeNotAllowedError: (422, "JOB_TYPE_NOT_ALLOWED"),
    # Upstream/provider -> 502/503
    MarketDataUnavailableError: (503, "MARKET_DATA_UNAVAILABLE"),
    InvalidMarketDataError: (502, "INVALID_MARKET_DATA"),
    ProviderRequestError: (502, "PROVIDER_ERROR"),
    EmbeddingProviderError: (503, "EMBEDDING_PROVIDER_ERROR"),
    TutorModelProviderError: (503, "TUTOR_MODEL_PROVIDER_ERROR"),
    TransientInfrastructureError: (503, "TRANSIENT_INFRASTRUCTURE_ERROR"),
    LockAcquisitionError: (503, "LOCK_NOT_ACQUIRED"),
    # Identity/authentication for integration clients (n8n) -> 401
    IntegrationAuthenticationFailedError: (401, "AUTHENTICATION_FAILED"),
    # Internal
    PersistenceError: (500, "INTERNAL_ERROR"),
    DatabaseMappingError: (500, "INTERNAL_ERROR"),
}


def _correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", "unknown")


def _resolve_status_and_code(exc: StockResearchError) -> tuple[int, str]:
    mapped = _EXCEPTION_STATUS_MAP.get(type(exc))
    if mapped is not None:
        return mapped
    for exc_type, (status_code, code) in _EXCEPTION_STATUS_MAP.items():
        if isinstance(exc, exc_type):
            return status_code, code
    # An application exception we know about but haven't explicitly
    # classified - treat as a client-correctable error, not a server bug.
    return status.HTTP_400_BAD_REQUEST, "APPLICATION_ERROR"


async def stock_research_error_handler(request: Request, exc: StockResearchError) -> JSONResponse:
    status_code, code = _resolve_status_and_code(exc)
    body = ApiError(
        error=ApiErrorBody(code=code, message=str(exc), correlation_id=_correlation_id(request))
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        ApiErrorDetail(
            field=".".join(str(part) for part in error["loc"] if part != "body") or None,
            message=error["msg"],
        )
        for error in exc.errors()
    ]
    body = ApiError(
        error=ApiErrorBody(
            code="VALIDATION_ERROR", message="The request failed validation.", details=details,
            correlation_id=_correlation_id(request),
        )
    )
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=body.model_dump())


_HTTP_STATUS_CODES: dict[int, str] = {
    401: "AUTHENTICATION_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    429: "RATE_LIMIT_EXCEEDED",
}


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
    message = exc.detail if isinstance(exc.detail, str) and exc.detail else "The request could not be completed."
    body = ApiError(error=ApiErrorBody(code=code, message=message, correlation_id=_correlation_id(request)))
    headers = getattr(exc, "headers", None)
    return JSONResponse(status_code=exc.status_code, content=body.model_dump(), headers=headers)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Unhandled exception", extra={"correlation_id": _correlation_id(request), "path": request.url.path}
    )
    body = ApiError(
        error=ApiErrorBody(
            code="INTERNAL_ERROR", message="An unexpected error occurred.",
            correlation_id=_correlation_id(request),
        )
    )
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=body.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StockResearchError, stock_research_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
