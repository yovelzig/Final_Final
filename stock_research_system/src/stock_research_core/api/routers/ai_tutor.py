"""`/api/v1/tutor`: grounded AI-tutor conversations across all 6
`TutorContextType` values.

Every route dispatches to the *existing* `GroundedAITutorService` (via
`LessonTutorService`/`ScenarioTutorService`/`PortfolioTutorService` for
the context types that need freshly computed structured context) - no
retrieval, grounding, or guardrail logic is duplicated here. Every
conversation is always scoped to the caller's own `learner_id`;
`AskResponse`/`CitationResponse` structurally exclude chunk IDs,
embedding vectors, and raw prompt text. Question submission is
rate-limited per caller.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from stock_research_core.api.dependencies import (
    ensure_owned_by_learner,
    get_ai_tutor_service,
    get_lesson_tutor_service,
    get_portfolio_tutor_service,
    get_scenario_tutor_service,
    get_uow_factory,
    rate_limit,
    require_learner,
    require_learner_identity,
)
from stock_research_core.api.schemas.ai_tutor import (
    AskQuestionRequest,
    AskResponse,
    CreateConversationRequest,
    TutorConversationResponse,
    TutorMessageResponse,
)
from stock_research_core.application.ai_tutor.lesson_tutor import LessonTutorService
from stock_research_core.application.ai_tutor.models import TutorContext
from stock_research_core.application.ai_tutor.portfolio_tutor import PortfolioTutorService
from stock_research_core.application.ai_tutor.scenario_tutor import ScenarioTutorService
from stock_research_core.application.ai_tutor.service import GroundedAITutorService
from stock_research_core.application.exceptions import TutorConversationNotFoundError
from stock_research_core.application.identity.models import AuthenticatedPrincipal
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.domain.ai_tutor.models import TutorConversation

router = APIRouter()

_DEFAULT_MESSAGE_LIMIT = 20


async def _get_owned_conversation(
    uow: UnitOfWorkPort, conversation_id: UUID, principal: AuthenticatedPrincipal
) -> TutorConversation:
    conversation = await uow.tutor_conversations.get_conversation(conversation_id)
    if conversation is None:
        raise TutorConversationNotFoundError(f"No tutor conversation found with id '{conversation_id}'.")
    ensure_owned_by_learner(
        conversation.learner_id, principal, not_found_error=TutorConversationNotFoundError,
        message=f"No tutor conversation found with id '{conversation_id}'.",
    )
    return conversation


@router.post("/conversations", response_model=TutorConversationResponse, status_code=201)
async def create_conversation(
    payload: CreateConversationRequest,
    learner_id: Annotated[UUID, Depends(require_learner_identity)],
    tutor_service: Annotated[GroundedAITutorService, Depends(get_ai_tutor_service)],
    lesson_tutor: Annotated[LessonTutorService, Depends(get_lesson_tutor_service)],
    scenario_tutor: Annotated[ScenarioTutorService, Depends(get_scenario_tutor_service)],
    portfolio_tutor: Annotated[PortfolioTutorService, Depends(get_portfolio_tutor_service)],
) -> TutorConversationResponse:
    if payload.context_type == TutorContextType.GENERAL_EDUCATION:
        conversation = await tutor_service.create_conversation(
            learner_id=learner_id,
            context=TutorContext(context_type=TutorContextType.GENERAL_EDUCATION, learner_id=learner_id),
        )
    elif payload.context_type == TutorContextType.LESSON_HELP:
        conversation = await lesson_tutor.create_lesson_conversation(
            learner_id=learner_id, lesson_id=payload.lesson_id
        )
    elif payload.context_type == TutorContextType.EXERCISE_HELP:
        conversation = await lesson_tutor.create_exercise_help_conversation(
            learner_id=learner_id, exercise_id=payload.exercise_id
        )
    elif payload.context_type == TutorContextType.SCENARIO_BEFORE_DECISION:
        conversation = await scenario_tutor.create_before_decision_conversation(
            learner_id=learner_id, scenario_id=payload.scenario_id, submission_id=payload.submission_id
        )
    elif payload.context_type == TutorContextType.SCENARIO_AFTER_REVEAL:
        conversation = await scenario_tutor.create_after_reveal_conversation(
            learner_id=learner_id, submission_id=payload.submission_id
        )
    else:
        conversation = await portfolio_tutor.create_portfolio_conversation(
            learner_id=learner_id, portfolio_id=payload.portfolio_id, as_of=payload.as_of
        )
    return TutorConversationResponse.from_domain(conversation)


@router.get("/conversations", response_model=list[TutorConversationResponse])
async def list_conversations(
    learner_id: Annotated[UUID, Depends(require_learner_identity)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
) -> list[TutorConversationResponse]:
    async with uow_factory() as uow:
        conversations = await uow.tutor_conversations.list_active_conversations_for_learner(learner_id)
    return [TutorConversationResponse.from_domain(c) for c in conversations]


@router.get("/conversations/{conversation_id}", response_model=TutorConversationResponse)
async def get_conversation(
    conversation_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
) -> TutorConversationResponse:
    async with uow_factory() as uow:
        conversation = await _get_owned_conversation(uow, conversation_id, principal)
    return TutorConversationResponse.from_domain(conversation)


@router.post(
    "/conversations/{conversation_id}/messages", response_model=AskResponse,
    dependencies=[Depends(rate_limit(action="tutor_question", limit=20, window_seconds=60))],
)
async def ask_question(
    conversation_id: UUID,
    payload: AskQuestionRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    tutor_service: Annotated[GroundedAITutorService, Depends(get_ai_tutor_service)],
    lesson_tutor: Annotated[LessonTutorService, Depends(get_lesson_tutor_service)],
    scenario_tutor: Annotated[ScenarioTutorService, Depends(get_scenario_tutor_service)],
    portfolio_tutor: Annotated[PortfolioTutorService, Depends(get_portfolio_tutor_service)],
) -> AskResponse:
    async with uow_factory() as uow:
        conversation = await _get_owned_conversation(uow, conversation_id, principal)

    if conversation.context_type in (TutorContextType.LESSON_HELP, TutorContextType.EXERCISE_HELP):
        response = await lesson_tutor.ask(
            conversation_id=conversation_id, question=payload.question,
            exercise_submitted=payload.exercise_submitted, top_k=payload.top_k,
        )
    elif conversation.context_type in (
        TutorContextType.SCENARIO_BEFORE_DECISION, TutorContextType.SCENARIO_AFTER_REVEAL,
    ):
        response = await scenario_tutor.ask(
            conversation_id=conversation_id, question=payload.question, top_k=payload.top_k
        )
    elif conversation.context_type == TutorContextType.PORTFOLIO_EXPLANATION:
        response = await portfolio_tutor.ask(
            conversation_id=conversation_id, question=payload.question, as_of=payload.as_of,
            top_k=payload.top_k,
        )
    else:
        response = await tutor_service.ask(
            conversation_id=conversation_id, question=payload.question, top_k=payload.top_k
        )
    return AskResponse.from_domain(response)


@router.post("/conversations/{conversation_id}/close", response_model=TutorConversationResponse)
async def close_conversation(
    conversation_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    tutor_service: Annotated[GroundedAITutorService, Depends(get_ai_tutor_service)],
) -> TutorConversationResponse:
    async with uow_factory() as uow:
        await _get_owned_conversation(uow, conversation_id, principal)
    conversation = await tutor_service.close_conversation(conversation_id)
    return TutorConversationResponse.from_domain(conversation)


@router.get("/conversations/{conversation_id}/messages", response_model=list[TutorMessageResponse])
async def list_messages(
    conversation_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_learner)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    limit: int = _DEFAULT_MESSAGE_LIMIT,
) -> list[TutorMessageResponse]:
    async with uow_factory() as uow:
        await _get_owned_conversation(uow, conversation_id, principal)
        messages = await uow.tutor_conversations.list_recent_messages(conversation_id, limit=limit)
    return [TutorMessageResponse.from_domain(m) for m in messages]
