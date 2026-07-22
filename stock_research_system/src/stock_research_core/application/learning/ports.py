"""Application-level repository contracts for the learning platform.

Pure `Protocol` definitions describing what the persistence layer does,
not how. No SQLAlchemy (or any other infrastructure library) is
imported here; concrete implementations live under
`stock_research_core.infrastructure.database`.

A couple of lookup-by-id methods (`AttemptRepositoryPort.get_attempt`,
`CurriculumRepositoryPort.get_exercise`) are not explicitly listed in
the original spec but are required for `LearningService.submit_answer`
to load the attempt/exercise it is grading - the same pattern already
used for `get_skill`/`get_lesson`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from stock_research_core.domain.learning.models import (
    Exercise,
    ExerciseAnswer,
    ExerciseAttempt,
    ExerciseOption,
    LearnerProfile,
    LearningModule,
    LearningPath,
    Lesson,
    Misconception,
    Skill,
    SkillMastery,
    UserProgress,
)


class LearnerRepositoryPort(Protocol):
    """Persists and retrieves `LearnerProfile` objects."""

    async def create(self, learner: LearnerProfile) -> LearnerProfile: ...

    async def get(self, learner_id: UUID) -> LearnerProfile | None: ...

    async def update(self, learner: LearnerProfile) -> LearnerProfile: ...

    async def set_active(self, learner_id: UUID, active: bool) -> LearnerProfile: ...


class CurriculumRepositoryPort(Protocol):
    """Persists and queries the curriculum hierarchy.

    All listing methods return results in deterministic `position` order.
    """

    async def upsert_skill(self, skill: Skill) -> Skill: ...

    async def get_skill(self, skill_id: UUID) -> Skill | None: ...

    async def list_skills(self, active_only: bool = True) -> list[Skill]: ...

    async def upsert_path(self, path: LearningPath) -> LearningPath: ...

    async def list_paths(self, published_only: bool = True) -> list[LearningPath]: ...

    async def get_path(self, path_id: UUID) -> LearningPath | None: ...

    async def upsert_module(self, module: LearningModule) -> LearningModule: ...

    async def list_modules(self, path_id: UUID) -> list[LearningModule]: ...

    async def get_module(self, module_id: UUID) -> LearningModule | None: ...

    async def upsert_lesson(self, lesson: Lesson) -> Lesson: ...

    async def get_lesson(self, lesson_id: UUID) -> Lesson | None: ...

    async def list_lessons(self, module_id: UUID) -> list[Lesson]: ...

    async def upsert_exercise(self, exercise: Exercise) -> Exercise: ...

    async def get_exercise(self, exercise_id: UUID) -> Exercise | None: ...

    async def list_exercises(self, lesson_id: UUID) -> list[Exercise]: ...

    async def upsert_options(self, options: list[ExerciseOption]) -> int: ...

    async def list_options(self, exercise_id: UUID) -> list[ExerciseOption]: ...


class AttemptRepositoryPort(Protocol):
    """Persists and queries `ExerciseAttempt` / `ExerciseAnswer` objects."""

    async def create_attempt(self, attempt: ExerciseAttempt) -> ExerciseAttempt: ...

    async def get_attempt(self, attempt_id: UUID) -> ExerciseAttempt | None: ...

    async def save_answer(self, answer: ExerciseAnswer) -> ExerciseAnswer: ...

    async def update_attempt(self, attempt: ExerciseAttempt) -> ExerciseAttempt: ...

    async def list_attempts(
        self, learner_id: UUID, exercise_id: UUID | None = None
    ) -> list[ExerciseAttempt]: ...


class MasteryRepositoryPort(Protocol):
    """Persists and queries `SkillMastery` objects. Unique per (learner, skill)."""

    async def upsert(self, mastery: SkillMastery) -> SkillMastery: ...

    async def get(self, learner_id: UUID, skill_id: UUID) -> SkillMastery | None: ...

    async def list_for_learner(self, learner_id: UUID) -> list[SkillMastery]: ...


class ProgressRepositoryPort(Protocol):
    """Persists and queries `UserProgress` objects."""

    async def upsert(self, progress: UserProgress) -> UserProgress: ...

    async def get_lesson_progress(
        self, learner_id: UUID, lesson_id: UUID
    ) -> UserProgress | None: ...

    async def list_for_learner(self, learner_id: UUID) -> list[UserProgress]: ...


class MisconceptionRepositoryPort(Protocol):
    """Persists and queries `Misconception` objects."""

    async def upsert(self, misconception: Misconception) -> Misconception: ...

    async def list_active(self, learner_id: UUID) -> list[Misconception]: ...

    async def resolve(self, misconception_id: UUID, resolved_at: datetime) -> Misconception: ...
