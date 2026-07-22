"""`/api/v1/coach`: the Phase 12 personalized learning orchestrator
(spec section 24).

Every route derives the caller's learner id from the authenticated
principal (`require_learner_identity`) - never from a path or body
parameter - and every thread/run/proposal lookup goes through
`PersonalizedLearningOrchestratorService`'s own ownership checks, which
raise a 404-mapped not-found error rather than ever revealing another
learner's thread exists. Streaming endpoints use a plain authenticated
`fetch()`-compatible Server-Sent-Events response (not `EventSource`,
which cannot send an `Authorization` header) - see the frontend's
`use-learning-coach-stream.ts`.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import StreamingResponse

from stock_research_core.api.dependencies import get_learning_orchestrator_service, rate_limit, require_learner_identity
from stock_research_core.api.schemas.learning_orchestrator import (
    CreateThreadRequest,
    LearningCoachApprovalRequest,
    LearningCoachEventResponse,
    LearningCoachRunResponse,
    LearningCoachThreadListResponse,
    LearningCoachThreadResponse,
    StartRunRequest,
)
from stock_research_core.application.learning_orchestrator.models import LearningApprovalRequest
from stock_research_core.application.learning_orchestrator.service import PersonalizedLearningOrchestratorService
from stock_research_core.domain.learning_orchestrator.enums import LearningOrchestratorThreadStatus

router = APIRouter()

_DEFAULT_LIST_LIMIT = 50
_RUN_RATE_LIMIT = 20
_RUN_RATE_LIMIT_WINDOW_SECONDS = 60


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def _sse_stream(events: AsyncIterator[dict[str, Any]]) -> AsyncIterator[str]:
    async for event in events:
        yield _sse(event)


def _streaming_response(events: AsyncIterator[dict[str, Any]]) -> StreamingResponse:
    return StreamingResponse(
        _sse_stream(events), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# -- threads -----------------------------------------------


@router.post("/threads", response_model=LearningCoachThreadResponse, status_code=status.HTTP_201_CREATED)
async def create_thread(
    payload: CreateThreadRequest,
    learner_id: Annotated[UUID, Depends(require_learner_identity)],
    service: Annotated[PersonalizedLearningOrchestratorService, Depends(get_learning_orchestrator_service)],
) -> LearningCoachThreadResponse:
    thread = await service.create_thread(
        learner_id=learner_id, title=payload.title, initial_context_type=payload.initial_context_type
    )
    return LearningCoachThreadResponse.from_domain(thread)


@router.get("/threads", response_model=LearningCoachThreadListResponse)
async def list_threads(
    learner_id: Annotated[UUID, Depends(require_learner_identity)],
    service: Annotated[PersonalizedLearningOrchestratorService, Depends(get_learning_orchestrator_service)],
    thread_status: Annotated[LearningOrchestratorThreadStatus | None, Query(alias="status")] = None,
    limit: int = Query(default=_DEFAULT_LIST_LIMIT, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> LearningCoachThreadListResponse:
    threads, total = await service.list_threads(learner_id=learner_id, status=thread_status, limit=limit, offset=offset)
    return LearningCoachThreadListResponse(
        items=[LearningCoachThreadResponse.from_domain(thread) for thread in threads],
        total=total, limit=limit, offset=offset,
    )


@router.get("/threads/{thread_id}", response_model=LearningCoachThreadResponse)
async def get_thread(
    thread_id: UUID,
    learner_id: Annotated[UUID, Depends(require_learner_identity)],
    service: Annotated[PersonalizedLearningOrchestratorService, Depends(get_learning_orchestrator_service)],
) -> LearningCoachThreadResponse:
    thread = await service.get_thread(learner_id=learner_id, thread_id=thread_id)
    return LearningCoachThreadResponse.from_domain(thread)


@router.post("/threads/{thread_id}/close", response_model=LearningCoachThreadResponse)
async def close_thread(
    thread_id: UUID,
    learner_id: Annotated[UUID, Depends(require_learner_identity)],
    service: Annotated[PersonalizedLearningOrchestratorService, Depends(get_learning_orchestrator_service)],
) -> LearningCoachThreadResponse:
    thread = await service.close_thread(learner_id=learner_id, thread_id=thread_id)
    return LearningCoachThreadResponse.from_domain(thread)


# -- runs -----------------------------------------------


@router.post(
    "/threads/{thread_id}/runs", response_model=LearningCoachRunResponse, status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit(action="coach_run", limit=_RUN_RATE_LIMIT, window_seconds=_RUN_RATE_LIMIT_WINDOW_SECONDS))],
)
async def start_run(
    thread_id: UUID,
    payload: StartRunRequest,
    learner_id: Annotated[UUID, Depends(require_learner_identity)],
    service: Annotated[PersonalizedLearningOrchestratorService, Depends(get_learning_orchestrator_service)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
) -> LearningCoachRunResponse:
    run = await service.start_run(
        learner_id=learner_id, thread_id=thread_id, user_input=payload.user_input,
        idempotency_key=idempotency_key, context_references=payload.context_references,
    )
    return LearningCoachRunResponse.from_domain(run)


@router.post(
    "/threads/{thread_id}/runs/stream",
    dependencies=[Depends(rate_limit(action="coach_run", limit=_RUN_RATE_LIMIT, window_seconds=_RUN_RATE_LIMIT_WINDOW_SECONDS))],
)
async def stream_start_run(
    thread_id: UUID,
    payload: StartRunRequest,
    learner_id: Annotated[UUID, Depends(require_learner_identity)],
    service: Annotated[PersonalizedLearningOrchestratorService, Depends(get_learning_orchestrator_service)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
) -> StreamingResponse:
    events = service.stream_start_run(
        learner_id=learner_id, thread_id=thread_id, user_input=payload.user_input,
        idempotency_key=idempotency_key, context_references=payload.context_references,
    )
    return _streaming_response(events)


@router.get("/runs/{run_id}", response_model=LearningCoachRunResponse)
async def get_run(
    run_id: UUID,
    learner_id: Annotated[UUID, Depends(require_learner_identity)],
    service: Annotated[PersonalizedLearningOrchestratorService, Depends(get_learning_orchestrator_service)],
) -> LearningCoachRunResponse:
    run = await service.get_run(learner_id=learner_id, run_id=run_id)
    return LearningCoachRunResponse.from_domain(run)


@router.get("/runs/{run_id}/events", response_model=list[LearningCoachEventResponse])
async def list_events(
    run_id: UUID,
    learner_id: Annotated[UUID, Depends(require_learner_identity)],
    service: Annotated[PersonalizedLearningOrchestratorService, Depends(get_learning_orchestrator_service)],
) -> list[LearningCoachEventResponse]:
    events = await service.list_events(learner_id=learner_id, run_id=run_id)
    return [LearningCoachEventResponse.from_domain(event) for event in events]


@router.post("/runs/{run_id}/resume", response_model=LearningCoachRunResponse)
async def resume_run(
    run_id: UUID,
    payload: LearningCoachApprovalRequest,
    learner_id: Annotated[UUID, Depends(require_learner_identity)],
    service: Annotated[PersonalizedLearningOrchestratorService, Depends(get_learning_orchestrator_service)],
) -> LearningCoachRunResponse:
    approval = LearningApprovalRequest(
        proposal_id=payload.proposal_id, decision=payload.decision, edited_parameters=payload.edited_parameters,
    )
    run = await service.resume_run(learner_id=learner_id, run_id=run_id, approval=approval)
    return LearningCoachRunResponse.from_domain(run)


@router.post("/runs/{run_id}/resume/stream")
async def stream_resume_run(
    run_id: UUID,
    payload: LearningCoachApprovalRequest,
    learner_id: Annotated[UUID, Depends(require_learner_identity)],
    service: Annotated[PersonalizedLearningOrchestratorService, Depends(get_learning_orchestrator_service)],
) -> StreamingResponse:
    approval = LearningApprovalRequest(
        proposal_id=payload.proposal_id, decision=payload.decision, edited_parameters=payload.edited_parameters,
    )
    events = service.stream_resume_run(learner_id=learner_id, run_id=run_id, approval=approval)
    return _streaming_response(events)


@router.post("/runs/{run_id}/cancel", response_model=LearningCoachRunResponse)
async def cancel_run(
    run_id: UUID,
    learner_id: Annotated[UUID, Depends(require_learner_identity)],
    service: Annotated[PersonalizedLearningOrchestratorService, Depends(get_learning_orchestrator_service)],
) -> LearningCoachRunResponse:
    run = await service.cancel_run(learner_id=learner_id, run_id=run_id)
    return LearningCoachRunResponse.from_domain(run)
