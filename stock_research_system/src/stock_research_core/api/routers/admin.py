"""`/api/v1/admin`: account administration (ADMIN-only), curriculum
authoring (CONTENT_EDITOR-or-ADMIN), and knowledge-base management
(CONTENT_EDITOR-or-ADMIN).

Curriculum authoring calls the existing `CurriculumRepositoryPort`
upsert methods directly through the Unit of Work - the same pattern
already used by the seed scripts and by `LearningService` itself for
reads; there is no separate "authoring service" to duplicate, and no
SQLAlchemy is touched directly. Knowledge-base ingestion always flows
through the existing `KnowledgeIngestionService`; the file-upload
endpoint writes to a bounded temporary file and always cleans it up,
even on failure.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile

from stock_research_core.api.dependencies import (
    get_identity_service,
    get_knowledge_ingestion_service,
    get_uow_factory,
    require_admin,
    require_content_editor,
)
from stock_research_core.api.pagination import PaginationParams, pagination_params, paginated
from stock_research_core.api.schemas.admin import (
    AdminExerciseResponse,
    AdminLessonResponse,
    AdminModuleResponse,
    AdminPathResponse,
    IngestionRunResponse,
    IngestionSummaryResponse,
    KnowledgeDocumentResponse,
    RevokeSessionsResponse,
    SkillResponse,
    UpsertExerciseRequest,
    UpsertLessonRequest,
    UpsertModuleRequest,
    UpsertPathRequest,
    UpsertSkillRequest,
)
from stock_research_core.api.schemas.auth import PublicAccount
from stock_research_core.api.schemas.common import PaginatedResponse
from stock_research_core.application.ai_tutor.knowledge_ingestion import KnowledgeIngestionService
from stock_research_core.application.exceptions import (
    AccountNotFoundError,
    LearningModuleNotFoundError,
    LearningPathNotFoundError,
    LessonNotFoundError,
    UnsupportedDocumentError,
)
from stock_research_core.application.identity.service import IdentityService
from stock_research_core.domain.ai_tutor.enums import KnowledgeApprovalStatus
from stock_research_core.domain.identity.enums import AccountRole, AccountStatus
from stock_research_core.domain.learning.models import Exercise, ExerciseOption, LearningModule, LearningPath, Lesson, Skill
from stock_research_core.domain.models import utc_now

router = APIRouter()

_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB, matches the parser's own bound (defense in depth)
_ALLOWED_UPLOAD_SUFFIXES = {".md", ".txt", ".pdf", ".docx"}


# -- accounts (ADMIN only) -----------------------------------------------


@router.get(
    "/accounts", response_model=PaginatedResponse[PublicAccount], dependencies=[Depends(require_admin)]
)
async def list_accounts(
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    role: AccountRole | None = None,
    status: AccountStatus | None = None,
) -> PaginatedResponse[PublicAccount]:
    async with uow_factory() as uow:
        accounts, total = await uow.user_accounts.list_accounts(
            role=role, status=status, limit=pagination.limit, offset=pagination.offset
        )
    return paginated(items=[PublicAccount.from_domain(a) for a in accounts], total=total, params=pagination)


@router.get("/accounts/{account_id}", response_model=PublicAccount, dependencies=[Depends(require_admin)])
async def get_account(
    account_id: UUID, uow_factory: Annotated[object, Depends(get_uow_factory)]
) -> PublicAccount:
    async with uow_factory() as uow:
        account = await uow.user_accounts.get_by_id(account_id)
    if account is None:
        raise AccountNotFoundError(f"No account found with id '{account_id}'.")
    return PublicAccount.from_domain(account)


@router.post("/accounts/{account_id}/disable", response_model=PublicAccount, dependencies=[Depends(require_admin)])
async def disable_account(
    account_id: UUID, uow_factory: Annotated[object, Depends(get_uow_factory)]
) -> PublicAccount:
    async with uow_factory() as uow:
        account = await uow.user_accounts.update_status(
            account_id, status=AccountStatus.DISABLED, locked_until=None
        )
        await uow.commit()
    return PublicAccount.from_domain(account)


@router.post("/accounts/{account_id}/enable", response_model=PublicAccount, dependencies=[Depends(require_admin)])
async def enable_account(
    account_id: UUID, uow_factory: Annotated[object, Depends(get_uow_factory)]
) -> PublicAccount:
    async with uow_factory() as uow:
        account = await uow.user_accounts.update_status(
            account_id, status=AccountStatus.ACTIVE, locked_until=None
        )
        await uow.commit()
    return PublicAccount.from_domain(account)


@router.post(
    "/accounts/{account_id}/revoke-sessions", response_model=RevokeSessionsResponse,
    dependencies=[Depends(require_admin)],
)
async def revoke_sessions(
    account_id: UUID, identity_service: Annotated[IdentityService, Depends(get_identity_service)]
) -> RevokeSessionsResponse:
    count = await identity_service.logout_all(account_id=account_id, correlation_id="admin-revoke-sessions")
    return RevokeSessionsResponse(revoked_session_count=count)


# -- curriculum authoring (CONTENT_EDITOR or ADMIN) -----------------------------------------------


@router.put(
    "/curriculum/skills", response_model=SkillResponse, dependencies=[Depends(require_content_editor)]
)
async def upsert_skill(
    payload: UpsertSkillRequest, uow_factory: Annotated[object, Depends(get_uow_factory)]
) -> SkillResponse:
    skill = Skill(
        **({"skill_id": payload.skill_id} if payload.skill_id else {}), code=payload.code, name=payload.name,
        description=payload.description, category=payload.category, difficulty=payload.difficulty,
        prerequisite_skill_ids=payload.prerequisite_skill_ids, active=payload.active,
    )
    async with uow_factory() as uow:
        stored = await uow.curriculum.upsert_skill(skill)
        await uow.commit()
    return SkillResponse.from_domain(stored)


@router.put(
    "/curriculum/paths", response_model=AdminPathResponse, dependencies=[Depends(require_content_editor)]
)
async def upsert_path(
    payload: UpsertPathRequest, uow_factory: Annotated[object, Depends(get_uow_factory)]
) -> AdminPathResponse:
    path = LearningPath(
        **({"path_id": payload.path_id} if payload.path_id else {}), code=payload.code, title=payload.title,
        description=payload.description, difficulty=payload.difficulty, position=payload.position,
        estimated_minutes=payload.estimated_minutes, published=payload.published,
    )
    async with uow_factory() as uow:
        stored = await uow.curriculum.upsert_path(path)
        await uow.commit()
    return AdminPathResponse.from_domain(stored)


@router.put(
    "/curriculum/paths/{path_id}/modules", response_model=AdminModuleResponse,
    dependencies=[Depends(require_content_editor)],
)
async def upsert_module(
    path_id: UUID, payload: UpsertModuleRequest, uow_factory: Annotated[object, Depends(get_uow_factory)]
) -> AdminModuleResponse:
    async with uow_factory() as uow:
        path = await uow.curriculum.get_path(path_id)
        if path is None:
            raise LearningPathNotFoundError(f"No learning path found with id '{path_id}'.")
        module = LearningModule(
            **({"module_id": payload.module_id} if payload.module_id else {}), path_id=path_id,
            code=payload.code, title=payload.title, description=payload.description,
            position=payload.position, estimated_minutes=payload.estimated_minutes,
            published=payload.published,
        )
        stored = await uow.curriculum.upsert_module(module)
        await uow.commit()
    return AdminModuleResponse.from_domain(stored)


@router.put(
    "/curriculum/modules/{module_id}/lessons", response_model=AdminLessonResponse,
    dependencies=[Depends(require_content_editor)],
)
async def upsert_lesson(
    module_id: UUID, payload: UpsertLessonRequest, uow_factory: Annotated[object, Depends(get_uow_factory)]
) -> AdminLessonResponse:
    async with uow_factory() as uow:
        module = await uow.curriculum.get_module(module_id)
        if module is None:
            raise LearningModuleNotFoundError(f"No learning module found with id '{module_id}'.")
        lesson = Lesson(
            **({"lesson_id": payload.lesson_id} if payload.lesson_id else {}), module_id=module_id,
            code=payload.code, title=payload.title, summary=payload.summary,
            content_markdown=payload.content_markdown, difficulty=payload.difficulty,
            status=payload.status, position=payload.position, estimated_minutes=payload.estimated_minutes,
            primary_skill_id=payload.primary_skill_id, secondary_skill_ids=payload.secondary_skill_ids,
        )
        stored = await uow.curriculum.upsert_lesson(lesson)
        await uow.commit()
    return AdminLessonResponse.from_domain(stored)


@router.put(
    "/curriculum/lessons/{lesson_id}/exercises", response_model=AdminExerciseResponse,
    dependencies=[Depends(require_content_editor)],
)
async def upsert_exercise(
    lesson_id: UUID, payload: UpsertExerciseRequest, uow_factory: Annotated[object, Depends(get_uow_factory)]
) -> AdminExerciseResponse:
    async with uow_factory() as uow:
        lesson = await uow.curriculum.get_lesson(lesson_id)
        if lesson is None:
            raise LessonNotFoundError(f"No lesson found with id '{lesson_id}'.")
        exercise = Exercise(
            **({"exercise_id": payload.exercise_id} if payload.exercise_id else {}), lesson_id=lesson_id,
            exercise_type=payload.exercise_type, prompt=payload.prompt, explanation=payload.explanation,
            difficulty=payload.difficulty, position=payload.position, skill_ids=payload.skill_ids,
            maximum_score=payload.maximum_score, passing_score=payload.passing_score, active=payload.active,
        )
        stored_exercise = await uow.curriculum.upsert_exercise(exercise)
        stored_options = []
        if payload.options:
            options = [
                ExerciseOption(
                    **({"option_id": o.option_id} if o.option_id else {}),
                    exercise_id=stored_exercise.exercise_id, option_key=o.option_key, content=o.content,
                    position=o.position, is_correct=o.is_correct, feedback=o.feedback,
                )
                for o in payload.options
            ]
            await uow.curriculum.upsert_options(options)
            stored_options = await uow.curriculum.list_options(stored_exercise.exercise_id)
        await uow.commit()
    return AdminExerciseResponse.from_domain(stored_exercise, stored_options)


# -- knowledge base (CONTENT_EDITOR or ADMIN) -----------------------------------------------


@router.post(
    "/knowledge/ingest-curriculum", response_model=IngestionSummaryResponse,
    dependencies=[Depends(require_content_editor)],
)
async def ingest_curriculum(
    ingestion_service: Annotated[KnowledgeIngestionService, Depends(get_knowledge_ingestion_service)],
) -> IngestionSummaryResponse:
    summary = await ingestion_service.ingest_curriculum()
    return IngestionSummaryResponse.from_domain(summary)


@router.post(
    "/knowledge/documents", response_model=IngestionSummaryResponse, status_code=201,
    dependencies=[Depends(require_content_editor)],
)
async def upload_document(
    ingestion_service: Annotated[KnowledgeIngestionService, Depends(get_knowledge_ingestion_service)],
    file: Annotated[UploadFile, File()],
    source_title: Annotated[str, Form(min_length=1, max_length=300)],
    approval_status: Annotated[KnowledgeApprovalStatus, Form()] = KnowledgeApprovalStatus.DRAFT,
    skill_ids: Annotated[str, Form()] = "",
) -> IngestionSummaryResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_UPLOAD_SUFFIXES:
        raise UnsupportedDocumentError(
            f"Unsupported file extension '{suffix}'. Supported: .md, .txt, .pdf, .docx"
        )

    parsed_skill_ids = [UUID(s.strip()) for s in skill_ids.split(",") if s.strip()]

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)
            written = 0
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > _MAX_UPLOAD_BYTES:
                    raise UnsupportedDocumentError(
                        f"Upload exceeds the {_MAX_UPLOAD_BYTES}-byte limit."
                    )
                tmp_file.write(chunk)

        summary = await ingestion_service.ingest_local_document(
            file_path=tmp_path, source_title=source_title, approval_status=approval_status,
            skill_ids=parsed_skill_ids, available_at=utc_now(),
        )
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
        await file.close()

    return IngestionSummaryResponse.from_domain(summary)


@router.get(
    "/knowledge/documents", response_model=list[KnowledgeDocumentResponse],
    dependencies=[Depends(require_content_editor)],
)
async def list_documents(
    uow_factory: Annotated[object, Depends(get_uow_factory)],
) -> list[KnowledgeDocumentResponse]:
    async with uow_factory() as uow:
        documents = await uow.knowledge.list_approved_documents()
    return [KnowledgeDocumentResponse.from_domain(d) for d in documents]


@router.get(
    "/knowledge/ingestion-runs", response_model=list[IngestionRunResponse],
    dependencies=[Depends(require_content_editor)],
)
async def list_ingestion_runs(
    uow_factory: Annotated[object, Depends(get_uow_factory)],
    limit: int = 10,
) -> list[IngestionRunResponse]:
    async with uow_factory() as uow:
        runs = await uow.knowledge.list_recent_ingestion_runs(limit=limit)
    return [IngestionRunResponse.from_domain(r) for r in runs]
