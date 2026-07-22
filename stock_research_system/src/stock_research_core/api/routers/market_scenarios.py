"""`/api/v1/scenarios`: the published historical-scenario catalog, the
learner-safe pre-decision view, and the submit/reveal decision
lifecycle.

`LearnerScenarioResponse` and `ScenarioRevealResponse` are always built
from the application layer's already-point-in-time-safe
`LearnerScenarioView`/`ScenarioReveal` - this router never touches a
`MarketBar` or `HistoricalMarketScenario` directly, so it cannot
accidentally leak a future bar ahead of the service's own guardrail.
Every submission endpoint is ownership-checked against the caller's own
`learner_id` before any read or mutation.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from stock_research_core.api.dependencies import (
    ensure_owned_by_learner,
    get_learning_service,
    get_scenario_service,
    get_uow_factory,
    require_learner,
)
from stock_research_core.api.schemas.market_scenarios import (
    LearnerScenarioResponse,
    ScenarioCatalogItemResponse,
    ScenarioRevealResponse,
    ScenarioSubmissionResponse,
    SubmitDecisionRequest,
)
from stock_research_core.application.exceptions import ScenarioSubmissionNotFoundError
from stock_research_core.application.identity.models import AuthenticatedPrincipal
from stock_research_core.application.learning.service import LearningService
from stock_research_core.application.market_scenarios.service import HistoricalMarketScenarioService
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.domain.market_scenarios.enums import MarketScenarioType
from stock_research_core.domain.market_scenarios.models import ScenarioSubmission

router = APIRouter()


async def _get_owned_submission(
    uow: UnitOfWorkPort, submission_id: UUID, principal: AuthenticatedPrincipal
) -> ScenarioSubmission:
    submission = await uow.scenario_submissions.get(submission_id)
    if submission is None:
        raise ScenarioSubmissionNotFoundError(f"No scenario submission found with id '{submission_id}'.")
    ensure_owned_by_learner(
        submission.learner_id, principal, not_found_error=ScenarioSubmissionNotFoundError,
        message=f"No scenario submission found with id '{submission_id}'.",
    )
    return submission


@router.get("", response_model=list[ScenarioCatalogItemResponse], dependencies=[Depends(require_learner)])
async def list_scenarios(
    scenario_service: Annotated[HistoricalMarketScenarioService, Depends(get_scenario_service)],
    skill_id: UUID | None = None,
    scenario_type: MarketScenarioType | None = None,
) -> list[ScenarioCatalogItemResponse]:
    items = await scenario_service.list_scenarios(skill_id=skill_id, scenario_type=scenario_type)
    return [ScenarioCatalogItemResponse.from_domain(item) for item in items]


@router.get("/{scenario_id}", response_model=LearnerScenarioResponse)
async def get_scenario(
    scenario_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    scenario_service: Annotated[HistoricalMarketScenarioService, Depends(get_scenario_service)],
) -> LearnerScenarioResponse:
    view = await scenario_service.get_learner_view(learner_id=principal.learner_id, scenario_id=scenario_id)
    return LearnerScenarioResponse.from_domain(view)


@router.post("/{scenario_id}/start", response_model=ScenarioSubmissionResponse, status_code=201)
async def start_scenario(
    scenario_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    learning_service: Annotated[LearningService, Depends(get_learning_service)],
    scenario_service: Annotated[HistoricalMarketScenarioService, Depends(get_scenario_service)],
) -> ScenarioSubmissionResponse:
    # `get_learner_view` already performs the learner-active / scenario-published
    # / focal-security-exists checks this composition would otherwise have to
    # duplicate; it also resolves the scenario's `exercise_id` for us.
    view = await scenario_service.get_learner_view(learner_id=principal.learner_id, scenario_id=scenario_id)
    attempt = await learning_service.start_exercise_attempt(
        learner_id=principal.learner_id, exercise_id=view.exercise_id
    )
    submission = await scenario_service.start_scenario(
        learner_id=principal.learner_id, scenario_id=scenario_id, exercise_attempt_id=attempt.attempt_id
    )
    return ScenarioSubmissionResponse.from_domain(submission)


@router.post("/submissions/{submission_id}/submit", response_model=ScenarioSubmissionResponse)
async def submit_decision(
    submission_id: UUID,
    payload: SubmitDecisionRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    scenario_service: Annotated[HistoricalMarketScenarioService, Depends(get_scenario_service)],
) -> ScenarioSubmissionResponse:
    async with uow_factory() as uow:
        await _get_owned_submission(uow, submission_id, principal)
    result = await scenario_service.submit_decision(
        submission_id=submission_id, selected_option_id=payload.selected_option_id,
        confidence_level=payload.confidence_level, learner_rationale=payload.learner_rationale,
    )
    return ScenarioSubmissionResponse.from_domain(result.submission)


@router.post("/submissions/{submission_id}/reveal", response_model=ScenarioRevealResponse)
async def reveal_submission(
    submission_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    scenario_service: Annotated[HistoricalMarketScenarioService, Depends(get_scenario_service)],
) -> ScenarioRevealResponse:
    async with uow_factory() as uow:
        await _get_owned_submission(uow, submission_id, principal)
    reveal = await scenario_service.reveal_outcome(submission_id=submission_id)
    return ScenarioRevealResponse.from_domain(reveal)


@router.get("/submissions/{submission_id}/reveal", response_model=ScenarioRevealResponse)
async def get_submission_reveal(
    submission_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    scenario_service: Annotated[HistoricalMarketScenarioService, Depends(get_scenario_service)],
) -> ScenarioRevealResponse:
    async with uow_factory() as uow:
        await _get_owned_submission(uow, submission_id, principal)
    reveal = await scenario_service.get_reveal(submission_id=submission_id)
    return ScenarioRevealResponse.from_domain(reveal)
