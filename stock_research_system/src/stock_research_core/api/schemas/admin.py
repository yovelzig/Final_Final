"""Request/response DTOs for `/api/v1/admin`: account administration,
CONTENT_EDITOR-or-ADMIN curriculum authoring, and knowledge-base
management.

Unlike the learner-facing curriculum schemas (`api/schemas/curriculum.py`),
`AdminExerciseOptionRequest`/`Response` DO carry `is_correct`/`feedback`
- these endpoints are gated by `require_content_editor` and are the one
place in the API authorized to see/set the answer key.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from stock_research_core.api.schemas.common import ApiSchema
from stock_research_core.application.ai_tutor.models import KnowledgeIngestionRunRecord, KnowledgeIngestionSummary
from stock_research_core.domain.ai_tutor.enums import (
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeIngestionRunStatus,
)
from stock_research_core.domain.ai_tutor.models import KnowledgeDocument
from stock_research_core.domain.identity.enums import AccountRole, AccountStatus
from stock_research_core.domain.learning.enums import DifficultyLevel, ExerciseType, FinancialSkillCategory, LessonStatus
from stock_research_core.domain.learning.models import Exercise, LearningModule, LearningPath, Lesson, Skill

# -- accounts -----------------------------------------------


class RevokeSessionsResponse(ApiSchema):
    revoked_session_count: int


# -- curriculum authoring -----------------------------------------------


class UpsertSkillRequest(ApiSchema):
    skill_id: UUID | None = None
    code: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=3000)
    category: FinancialSkillCategory
    difficulty: DifficultyLevel
    prerequisite_skill_ids: list[UUID] = Field(default_factory=list)
    active: bool = True


class SkillResponse(ApiSchema):
    skill_id: UUID
    code: str
    name: str
    description: str
    category: FinancialSkillCategory
    difficulty: DifficultyLevel
    prerequisite_skill_ids: list[UUID]
    active: bool

    @staticmethod
    def from_domain(skill: Skill) -> SkillResponse:
        return SkillResponse(
            skill_id=skill.skill_id, code=skill.code, name=skill.name, description=skill.description,
            category=skill.category, difficulty=skill.difficulty,
            prerequisite_skill_ids=list(skill.prerequisite_skill_ids), active=skill.active,
        )


class UpsertPathRequest(ApiSchema):
    path_id: UUID | None = None
    code: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=3000)
    difficulty: DifficultyLevel
    position: int = Field(ge=0)
    estimated_minutes: int = Field(gt=0)
    published: bool = False


class AdminPathResponse(ApiSchema):
    path_id: UUID
    code: str
    title: str
    description: str
    difficulty: DifficultyLevel
    position: int
    estimated_minutes: int
    published: bool

    @staticmethod
    def from_domain(path: LearningPath) -> AdminPathResponse:
        return AdminPathResponse(
            path_id=path.path_id, code=path.code, title=path.title, description=path.description,
            difficulty=path.difficulty, position=path.position, estimated_minutes=path.estimated_minutes,
            published=path.published,
        )


class UpsertModuleRequest(ApiSchema):
    module_id: UUID | None = None
    code: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=3000)
    position: int = Field(ge=0)
    estimated_minutes: int = Field(gt=0)
    published: bool = False


class AdminModuleResponse(ApiSchema):
    module_id: UUID
    path_id: UUID
    code: str
    title: str
    description: str
    position: int
    estimated_minutes: int
    published: bool

    @staticmethod
    def from_domain(module: LearningModule) -> AdminModuleResponse:
        return AdminModuleResponse(
            module_id=module.module_id, path_id=module.path_id, code=module.code, title=module.title,
            description=module.description, position=module.position,
            estimated_minutes=module.estimated_minutes, published=module.published,
        )


class UpsertLessonRequest(ApiSchema):
    lesson_id: UUID | None = None
    code: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    content_markdown: str = Field(min_length=1)
    difficulty: DifficultyLevel
    status: LessonStatus = LessonStatus.DRAFT
    position: int = Field(ge=0)
    estimated_minutes: int = Field(gt=0)
    primary_skill_id: UUID
    secondary_skill_ids: list[UUID] = Field(default_factory=list)


class AdminLessonResponse(ApiSchema):
    lesson_id: UUID
    module_id: UUID
    code: str
    title: str
    summary: str
    content_markdown: str
    difficulty: DifficultyLevel
    status: LessonStatus
    position: int
    estimated_minutes: int
    primary_skill_id: UUID
    secondary_skill_ids: list[UUID]

    @staticmethod
    def from_domain(lesson: Lesson) -> AdminLessonResponse:
        return AdminLessonResponse(
            lesson_id=lesson.lesson_id, module_id=lesson.module_id, code=lesson.code, title=lesson.title,
            summary=lesson.summary, content_markdown=lesson.content_markdown, difficulty=lesson.difficulty,
            status=lesson.status, position=lesson.position, estimated_minutes=lesson.estimated_minutes,
            primary_skill_id=lesson.primary_skill_id, secondary_skill_ids=list(lesson.secondary_skill_ids),
        )


class AdminExerciseOptionRequest(ApiSchema):
    option_id: UUID | None = None
    option_key: str = Field(min_length=1, max_length=50)
    content: str = Field(min_length=1, max_length=2000)
    position: int = Field(ge=0)
    is_correct: bool = False
    feedback: str | None = Field(default=None, max_length=2000)


class UpsertExerciseRequest(ApiSchema):
    exercise_id: UUID | None = None
    exercise_type: ExerciseType
    prompt: str = Field(min_length=1, max_length=3000)
    explanation: str = Field(min_length=1, max_length=3000)
    difficulty: DifficultyLevel
    position: int = Field(ge=0)
    skill_ids: list[UUID] = Field(min_length=1)
    maximum_score: float = Field(gt=0)
    passing_score: float = Field(ge=0)
    active: bool = True
    options: list[AdminExerciseOptionRequest] = Field(default_factory=list)


class AdminExerciseOptionResponse(ApiSchema):
    option_id: UUID
    option_key: str
    content: str
    position: int
    is_correct: bool
    feedback: str | None


class AdminExerciseResponse(ApiSchema):
    exercise_id: UUID
    lesson_id: UUID
    exercise_type: ExerciseType
    prompt: str
    explanation: str
    difficulty: DifficultyLevel
    position: int
    skill_ids: list[UUID]
    maximum_score: float
    passing_score: float
    active: bool
    options: list[AdminExerciseOptionResponse]

    @staticmethod
    def from_domain(exercise: Exercise, options) -> AdminExerciseResponse:  # noqa: ANN001
        return AdminExerciseResponse(
            exercise_id=exercise.exercise_id, lesson_id=exercise.lesson_id,
            exercise_type=exercise.exercise_type, prompt=exercise.prompt, explanation=exercise.explanation,
            difficulty=exercise.difficulty, position=exercise.position, skill_ids=list(exercise.skill_ids),
            maximum_score=exercise.maximum_score, passing_score=exercise.passing_score,
            active=exercise.active,
            options=[
                AdminExerciseOptionResponse(
                    option_id=o.option_id, option_key=o.option_key, content=o.content, position=o.position,
                    is_correct=o.is_correct, feedback=o.feedback,
                )
                for o in options
            ],
        )


# -- knowledge base -----------------------------------------------


class KnowledgeDocumentResponse(ApiSchema):
    document_id: UUID
    source_id: UUID
    title: str
    status: KnowledgeDocumentStatus
    approval_status: KnowledgeApprovalStatus
    language: str
    available_at: datetime
    lesson_id: UUID | None
    exercise_id: UUID | None
    scenario_id: UUID | None
    skill_ids: list[UUID]
    document_version: str

    @staticmethod
    def from_domain(document: KnowledgeDocument) -> KnowledgeDocumentResponse:
        return KnowledgeDocumentResponse(
            document_id=document.document_id, source_id=document.source_id, title=document.title,
            status=document.status, approval_status=document.approval_status, language=document.language,
            available_at=document.available_at, lesson_id=document.lesson_id,
            exercise_id=document.exercise_id, scenario_id=document.scenario_id,
            skill_ids=list(document.skill_ids), document_version=document.document_version,
        )


class IngestionRunResponse(ApiSchema):
    run_id: UUID
    source_id: UUID | None
    document_id: UUID | None
    status: KnowledgeIngestionRunStatus
    documents_processed: int
    chunks_created: int
    embeddings_created: int
    started_at: datetime
    completed_at: datetime | None
    error_type: str | None
    error_message: str | None

    @staticmethod
    def from_domain(run: KnowledgeIngestionRunRecord) -> IngestionRunResponse:
        return IngestionRunResponse(
            run_id=run.run_id, source_id=run.source_id, document_id=run.document_id, status=run.status,
            documents_processed=run.documents_processed, chunks_created=run.chunks_created,
            embeddings_created=run.embeddings_created, started_at=run.started_at,
            completed_at=run.completed_at, error_type=run.error_type, error_message=run.error_message,
        )


class IngestionSummaryResponse(ApiSchema):
    run: IngestionRunResponse
    sources_created: int
    sources_updated: int
    documents_created: int
    documents_updated: int
    documents_archived: int
    documents_skipped_unchanged: int
    chunks_created: int
    embeddings_created: int

    @staticmethod
    def from_domain(summary: KnowledgeIngestionSummary) -> IngestionSummaryResponse:
        return IngestionSummaryResponse(
            run=IngestionRunResponse.from_domain(summary.run), sources_created=summary.sources_created,
            sources_updated=summary.sources_updated, documents_created=summary.documents_created,
            documents_updated=summary.documents_updated, documents_archived=summary.documents_archived,
            documents_skipped_unchanged=summary.documents_skipped_unchanged,
            chunks_created=summary.chunks_created, embeddings_created=summary.embeddings_created,
        )
