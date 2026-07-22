"""`/api/v1/adaptive`: learning sessions, adaptive-decision lifecycle, and
diagnostic assessments.

Every session/decision/diagnostic endpoint is always scoped to the
caller's own `learner_id` and enforces ownership (raising the
resource's own not-found error, mapped to 404, ADMIN-bypassable via
the shared `ensure_owned_by_learner` helper) before returning or
mutating an existing resource - never trusts a `learner_id` from the
request body. Grading itself is never duplicated here: it always flows
through `LearningService.submit_answer` (directly, or via
`AdaptiveLearningOrchestrator.submit_recommended_answer`), the same
deterministic grading logic used by the curriculum router.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from stock_research_core.api.dependencies import (
    ensure_owned_by_learner,
    get_adaptive_learning_orchestrator,
    get_adaptive_learning_service,
    get_learning_service,
    get_uow_factory,
    require_learner,
)
from stock_research_core.api.schemas.adaptive_learning import (
    AdaptiveDecisionResponse,
    DiagnosticAssessmentResponse,
    DiagnosticItemResponse,
    DiagnosticStatusResponse,
    DiagnosticSummaryResponse,
    ExerciseRecommendationResponse,
    LearningSessionResponse,
    ReviewScheduleResponse,
    SessionActivityResponse,
    SessionSummaryResponse,
    StartDiagnosticItemRequest,
    StartDiagnosticRequest,
    StartRecommendedExerciseRequest,
    StartSessionRequest,
    SubmitDecisionAnswerRequest,
    SubmitDiagnosticResultRequest,
)
from stock_research_core.api.schemas.curriculum import AttemptResponse, ExerciseResponse, LessonResponse
from stock_research_core.application.adaptive_learning.models import DiagnosticSummary, SessionSummary
from stock_research_core.application.adaptive_learning.orchestrator import AdaptiveLearningOrchestrator
from stock_research_core.application.adaptive_learning.service import AdaptiveLearningService
from stock_research_core.application.exceptions import (
    AdaptiveDecisionNotFoundError,
    DiagnosticAssessmentItemNotFoundError,
    DiagnosticAssessmentNotFoundError,
    LearningSessionNotFoundError,
)
from stock_research_core.application.identity.models import AuthenticatedPrincipal
from stock_research_core.application.learning.service import LearningService
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.domain.adaptive_learning.models import AdaptiveDecision, DiagnosticAssessment, LearningSession
from stock_research_core.domain.learning.models import ExerciseAnswer

router = APIRouter()


def _session_summary_response(summary: SessionSummary) -> SessionSummaryResponse:
    return SessionSummaryResponse(
        session=LearningSessionResponse.from_domain(summary.session),
        activities=[SessionActivityResponse.from_domain(a) for a in summary.activities],
        mastery_changes=summary.mastery_changes,
        reviews_scheduled=[ReviewScheduleResponse.from_domain(r) for r in summary.reviews_scheduled],
    )


def _diagnostic_summary_response(summary: DiagnosticSummary) -> DiagnosticSummaryResponse:
    return DiagnosticSummaryResponse(
        assessment=DiagnosticAssessmentResponse.from_domain(summary.assessment),
        items=[DiagnosticItemResponse.from_domain(item) for item in summary.items],
        skill_results=summary.skill_results,
        skill_scores=summary.skill_scores,
        recommended_starting_skill_ids=list(summary.recommended_starting_skill_ids),
    )


async def _get_owned_session(
    uow: UnitOfWorkPort, session_id: UUID, principal: AuthenticatedPrincipal
) -> LearningSession:
    session = await uow.learning_sessions.get_session(session_id)
    if session is None:
        raise LearningSessionNotFoundError(f"No learning session found with id '{session_id}'.")
    ensure_owned_by_learner(
        session.learner_id, principal, not_found_error=LearningSessionNotFoundError,
        message=f"No learning session found with id '{session_id}'.",
    )
    return session


async def _get_owned_decision(
    uow: UnitOfWorkPort, decision_id: UUID, principal: AuthenticatedPrincipal
) -> AdaptiveDecision:
    decision = await uow.adaptive_decisions.get_decision(decision_id)
    if decision is None:
        raise AdaptiveDecisionNotFoundError(f"No adaptive decision found with id '{decision_id}'.")
    ensure_owned_by_learner(
        decision.learner_id, principal, not_found_error=AdaptiveDecisionNotFoundError,
        message=f"No adaptive decision found with id '{decision_id}'.",
    )
    return decision


async def _get_owned_assessment(
    uow: UnitOfWorkPort, assessment_id: UUID, principal: AuthenticatedPrincipal
) -> DiagnosticAssessment:
    assessment = await uow.diagnostics.get_assessment(assessment_id)
    if assessment is None:
        raise DiagnosticAssessmentNotFoundError(f"No diagnostic assessment found with id '{assessment_id}'.")
    ensure_owned_by_learner(
        assessment.learner_id, principal, not_found_error=DiagnosticAssessmentNotFoundError,
        message=f"No diagnostic assessment found with id '{assessment_id}'.",
    )
    return assessment


# -- sessions -----------------------------------------------


@router.post("/sessions", response_model=LearningSessionResponse, status_code=201)
async def start_session(
    payload: StartSessionRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    adaptive_service: Annotated[AdaptiveLearningService, Depends(get_adaptive_learning_service)],
) -> LearningSessionResponse:
    session = await adaptive_service.start_session(
        learner_id=principal.learner_id, session_type=payload.session_type, goal_minutes=payload.goal_minutes
    )
    return LearningSessionResponse.from_domain(session)


@router.get("/sessions/{session_id}", response_model=LearningSessionResponse)
async def get_session(
    session_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
) -> LearningSessionResponse:
    async with uow_factory() as uow:
        session = await _get_owned_session(uow, session_id, principal)
    return LearningSessionResponse.from_domain(session)


@router.post("/sessions/{session_id}/next", response_model=ExerciseRecommendationResponse)
async def get_next_recommendation(
    session_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    adaptive_service: Annotated[AdaptiveLearningService, Depends(get_adaptive_learning_service)],
) -> ExerciseRecommendationResponse:
    async with uow_factory() as uow:
        await _get_owned_session(uow, session_id, principal)

    recommendation = await adaptive_service.recommend_next(
        learner_id=principal.learner_id, session_id=session_id
    )

    exercise_response = None
    if recommendation.exercise is not None:
        async with uow_factory() as uow:
            options = await uow.curriculum.list_options(recommendation.exercise.exercise_id)
        exercise_response = ExerciseResponse.from_domain(recommendation.exercise, options)

    return ExerciseRecommendationResponse(
        decision=AdaptiveDecisionResponse.from_domain(recommendation.decision),
        exercise=exercise_response,
        lesson=LessonResponse.from_domain(recommendation.lesson) if recommendation.lesson else None,
    )


@router.post("/sessions/{session_id}/complete", response_model=SessionSummaryResponse)
async def complete_session(
    session_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    adaptive_service: Annotated[AdaptiveLearningService, Depends(get_adaptive_learning_service)],
) -> SessionSummaryResponse:
    async with uow_factory() as uow:
        await _get_owned_session(uow, session_id, principal)
    summary = await adaptive_service.complete_session(session_id=session_id)
    return _session_summary_response(summary)


# -- decisions -----------------------------------------------


@router.post("/decisions/{decision_id}/accept", response_model=AdaptiveDecisionResponse)
async def accept_decision(
    decision_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    adaptive_service: Annotated[AdaptiveLearningService, Depends(get_adaptive_learning_service)],
) -> AdaptiveDecisionResponse:
    async with uow_factory() as uow:
        await _get_owned_decision(uow, decision_id, principal)
    decision = await adaptive_service.accept_recommendation(decision_id=decision_id)
    return AdaptiveDecisionResponse.from_domain(decision)


@router.post("/decisions/{decision_id}/start", response_model=AttemptResponse)
async def start_decision_exercise(
    decision_id: UUID,
    payload: StartRecommendedExerciseRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    adaptive_service: Annotated[AdaptiveLearningService, Depends(get_adaptive_learning_service)],
) -> AttemptResponse:
    async with uow_factory() as uow:
        await _get_owned_decision(uow, decision_id, principal)
    attempt = await adaptive_service.start_recommended_exercise(
        decision_id=decision_id, confidence_level=payload.confidence_level
    )
    return AttemptResponse.from_domain(attempt)


@router.post("/decisions/{decision_id}/skip", response_model=AdaptiveDecisionResponse)
async def skip_decision(
    decision_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    adaptive_service: Annotated[AdaptiveLearningService, Depends(get_adaptive_learning_service)],
) -> AdaptiveDecisionResponse:
    async with uow_factory() as uow:
        await _get_owned_decision(uow, decision_id, principal)
    decision = await adaptive_service.skip_recommendation(decision_id=decision_id)
    return AdaptiveDecisionResponse.from_domain(decision)


@router.post("/decisions/{decision_id}/answers", response_model=SessionSummaryResponse)
async def submit_decision_answer(
    decision_id: UUID,
    payload: SubmitDecisionAnswerRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    orchestrator: Annotated[AdaptiveLearningOrchestrator, Depends(get_adaptive_learning_orchestrator)],
    adaptive_service: Annotated[AdaptiveLearningService, Depends(get_adaptive_learning_service)],
) -> SessionSummaryResponse:
    async with uow_factory() as uow:
        await _get_owned_decision(uow, decision_id, principal)
    attempt_id = await adaptive_service.get_attempt_id_for_decision(decision_id=decision_id)
    answer = ExerciseAnswer(
        attempt_id=attempt_id, selected_option_ids=payload.selected_option_ids,
        numeric_answer=payload.numeric_answer, text_answer=payload.text_answer,
        ordered_option_ids=payload.ordered_option_ids,
    )
    summary = await orchestrator.submit_recommended_answer(decision_id=decision_id, answer=answer)
    return _session_summary_response(summary)


# -- diagnostics -----------------------------------------------


@router.post("/diagnostics", response_model=DiagnosticSummaryResponse, status_code=201)
async def start_diagnostic(
    payload: StartDiagnosticRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    adaptive_service: Annotated[AdaptiveLearningService, Depends(get_adaptive_learning_service)],
) -> DiagnosticSummaryResponse:
    summary = await adaptive_service.start_diagnostic(
        learner_id=principal.learner_id, skill_ids=payload.skill_ids, maximum_items=payload.maximum_items
    )
    return _diagnostic_summary_response(summary)


@router.get("/diagnostics/{assessment_id}", response_model=DiagnosticStatusResponse)
async def get_diagnostic(
    assessment_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
) -> DiagnosticStatusResponse:
    async with uow_factory() as uow:
        assessment = await _get_owned_assessment(uow, assessment_id, principal)
        items = await uow.diagnostics.list_items(assessment_id)
    return DiagnosticStatusResponse(
        assessment=DiagnosticAssessmentResponse.from_domain(assessment),
        items=[DiagnosticItemResponse.from_domain(item) for item in items],
    )


@router.post("/diagnostics/{assessment_id}/items/{item_id}/start", response_model=AttemptResponse)
async def start_diagnostic_item(
    assessment_id: UUID,
    item_id: UUID,
    payload: StartDiagnosticItemRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    adaptive_service: Annotated[AdaptiveLearningService, Depends(get_adaptive_learning_service)],
) -> AttemptResponse:
    async with uow_factory() as uow:
        await _get_owned_assessment(uow, assessment_id, principal)
    attempt = await adaptive_service.start_diagnostic_item(
        assessment_id=assessment_id, item_id=item_id, confidence_level=payload.confidence_level
    )
    return AttemptResponse.from_domain(attempt)


@router.post(
    "/diagnostics/{assessment_id}/items/{item_id}/result", response_model=DiagnosticSummaryResponse
)
async def submit_diagnostic_result(
    assessment_id: UUID,
    item_id: UUID,
    payload: SubmitDiagnosticResultRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    learning_service: Annotated[LearningService, Depends(get_learning_service)],
    adaptive_service: Annotated[AdaptiveLearningService, Depends(get_adaptive_learning_service)],
) -> DiagnosticSummaryResponse:
    async with uow_factory() as uow:
        await _get_owned_assessment(uow, assessment_id, principal)
        item = await uow.diagnostics.get_item(item_id)
    if item is None or item.assessment_id != assessment_id or item.attempt_id is None:
        raise DiagnosticAssessmentItemNotFoundError(
            f"No started diagnostic item found with id '{item_id}' for assessment '{assessment_id}'."
        )
    answer = ExerciseAnswer(
        attempt_id=item.attempt_id, selected_option_ids=payload.selected_option_ids,
        numeric_answer=payload.numeric_answer, text_answer=payload.text_answer,
        ordered_option_ids=payload.ordered_option_ids,
    )
    result = await learning_service.submit_answer(attempt_id=item.attempt_id, answer=answer)
    summary = await adaptive_service.record_diagnostic_result(
        assessment_id=assessment_id, item_id=item_id, learning_activity_result=result
    )
    return _diagnostic_summary_response(summary)


@router.post("/diagnostics/{assessment_id}/complete", response_model=DiagnosticSummaryResponse)
async def complete_diagnostic(
    assessment_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    adaptive_service: Annotated[AdaptiveLearningService, Depends(get_adaptive_learning_service)],
) -> DiagnosticSummaryResponse:
    async with uow_factory() as uow:
        await _get_owned_assessment(uow, assessment_id, principal)
    summary = await adaptive_service.complete_diagnostic(assessment_id=assessment_id)
    return _diagnostic_summary_response(summary)
