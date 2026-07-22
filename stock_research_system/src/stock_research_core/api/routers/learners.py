"""`/api/v1/learners/*`: the caller's own learner profile and progress views.

Every route here derives the learner ID from `require_learner_identity`
(the authenticated principal's own `learner_id`) - never from a path or
body parameter - so a learner can never read or modify another
learner's data.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from stock_research_core.api.dependencies import get_uow_factory, require_learner_identity
from stock_research_core.api.pagination import PaginationParams, paginated, pagination_params
from stock_research_core.api.schemas.common import PaginatedResponse
from stock_research_core.api.schemas.learners import (
    DashboardResponse,
    LearnerProfileResponse,
    LearnerUpdateRequest,
    MisconceptionResponse,
    ProgressResponse,
    SkillMasteryResponse,
)
from stock_research_core.application.exceptions import LearnerNotFoundError
from stock_research_core.application.learning.service import LearningService

router = APIRouter()


@router.get("/learners/me", response_model=LearnerProfileResponse, summary="Get my learner profile")
async def get_my_profile(
    learner_id: Annotated[object, Depends(require_learner_identity)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
) -> LearnerProfileResponse:
    async with uow_factory() as uow:
        learner = await uow.learners.get(learner_id)
    if learner is None:
        raise LearnerNotFoundError("No learner profile found for this account.")
    return LearnerProfileResponse.from_domain(learner)


@router.patch("/learners/me", response_model=LearnerProfileResponse, summary="Update my learner profile")
async def update_my_profile(
    payload: LearnerUpdateRequest,
    learner_id: Annotated[object, Depends(require_learner_identity)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
) -> LearnerProfileResponse:
    async with uow_factory() as uow:
        learner = await uow.learners.get(learner_id)
        if learner is None:
            raise LearnerNotFoundError("No learner profile found for this account.")
        updates = payload.model_dump(exclude_unset=True, exclude_none=True)
        if updates:
            updated = learner.model_copy(update=updates)
            learner = await uow.learners.update(updated)
        await uow.commit()
    return LearnerProfileResponse.from_domain(learner)


@router.get("/learners/me/dashboard", response_model=DashboardResponse, summary="Get my learning dashboard")
async def get_my_dashboard(
    learner_id: Annotated[object, Depends(require_learner_identity)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
) -> DashboardResponse:
    dashboard = await LearningService(uow_factory).get_learner_dashboard(learner_id)
    return DashboardResponse(
        learner=LearnerProfileResponse.from_domain(dashboard.learner),
        active_path_id=dashboard.active_path.path_id if dashboard.active_path else None,
        current_lesson_id=dashboard.current_lesson.lesson_id if dashboard.current_lesson else None,
        completed_lessons=dashboard.completed_lessons, total_lessons=dashboard.total_lessons,
        current_streak_days=dashboard.current_streak_days, total_xp=dashboard.total_xp,
        skill_mastery=[SkillMasteryResponse.from_domain(m) for m in dashboard.skill_mastery],
        active_misconceptions=[MisconceptionResponse.from_domain(m) for m in dashboard.active_misconceptions],
    )


@router.get("/learners/me/mastery", response_model=PaginatedResponse[SkillMasteryResponse], summary="List my skill mastery")
async def list_my_mastery(
    learner_id: Annotated[object, Depends(require_learner_identity)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    params: Annotated[PaginationParams, Depends(pagination_params)],
) -> PaginatedResponse[SkillMasteryResponse]:
    async with uow_factory() as uow:
        all_mastery = await uow.mastery.list_for_learner(learner_id)
    page = all_mastery[params.offset : params.offset + params.limit]
    return paginated(items=[SkillMasteryResponse.from_domain(m) for m in page], total=len(all_mastery), params=params)


@router.get("/learners/me/progress", response_model=PaginatedResponse[ProgressResponse], summary="List my lesson/module/path progress")
async def list_my_progress(
    learner_id: Annotated[object, Depends(require_learner_identity)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    params: Annotated[PaginationParams, Depends(pagination_params)],
) -> PaginatedResponse[ProgressResponse]:
    async with uow_factory() as uow:
        all_progress = await uow.progress.list_for_learner(learner_id)
    page = all_progress[params.offset : params.offset + params.limit]
    return paginated(items=[ProgressResponse.from_domain(p) for p in page], total=len(all_progress), params=params)


@router.get(
    "/learners/me/misconceptions", response_model=PaginatedResponse[MisconceptionResponse],
    summary="List my active misconceptions",
)
async def list_my_misconceptions(
    learner_id: Annotated[object, Depends(require_learner_identity)],
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    params: Annotated[PaginationParams, Depends(pagination_params)],
) -> PaginatedResponse[MisconceptionResponse]:
    async with uow_factory() as uow:
        all_active = await uow.misconceptions.list_active(learner_id)
    page = all_active[params.offset : params.offset + params.limit]
    return paginated(
        items=[MisconceptionResponse.from_domain(m) for m in page], total=len(all_active), params=params
    )
