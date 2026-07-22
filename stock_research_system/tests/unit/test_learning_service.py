"""Unit tests for grading, mastery calculation, and `LearningService`.

Grading and mastery tests call the pure functions/calculator directly.
Service tests use fake repository implementations and a fake Unit of
Work - no SQLAlchemy or PostgreSQL is involved anywhere in this file.
"""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from stock_research_core.application.exceptions import InvalidGradingRequestError, PersistenceError
from stock_research_core.application.learning import grading as grading_module
from stock_research_core.application.learning import mastery as mastery_module
from stock_research_core.application.learning import service as service_module
from stock_research_core.application.learning.grading import grade_answer
from stock_research_core.application.learning.mastery import DeterministicMasteryCalculator
from stock_research_core.application.learning.service import LearningService
from stock_research_core.domain.learning import enums as learning_enums_module
from stock_research_core.domain.learning import models as learning_models_module
from stock_research_core.domain.learning.enums import (
    AttemptStatus,
    DifficultyLevel,
    ExerciseType,
    FinancialSkillCategory,
    LessonStatus,
    MasteryLevel,
    MisconceptionStatus,
    ProgressStatus,
)
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

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Grading tests
# ---------------------------------------------------------------------------


def _option(is_correct: bool, position: int = 0, key: str | None = None) -> ExerciseOption:
    return ExerciseOption(
        exercise_id=uuid4(),
        option_key=key or f"opt-{position}",
        content="content",
        position=position,
        is_correct=is_correct,
    )


def _exercise(exercise_type: ExerciseType, **overrides: object) -> Exercise:
    defaults = dict(
        lesson_id=uuid4(),
        exercise_type=exercise_type,
        prompt="prompt",
        explanation="explanation",
        difficulty=DifficultyLevel.BEGINNER,
        position=0,
        skill_ids=[uuid4()],
        maximum_score=1.0,
        passing_score=1.0,
    )
    defaults.update(overrides)
    return Exercise(**defaults)


def _answer(attempt_id: UUID, **overrides: object) -> ExerciseAnswer:
    defaults: dict = dict(attempt_id=attempt_id)
    defaults.update(overrides)
    return ExerciseAnswer(**defaults)


def test_single_choice_correct() -> None:
    correct = _option(True, 0, "a")
    incorrect = _option(False, 1, "b")
    exercise = _exercise(ExerciseType.SINGLE_CHOICE)
    answer = _answer(uuid4(), selected_option_ids=[correct.option_id])

    outcome = grade_answer(exercise, [correct, incorrect], answer)

    assert outcome.graded is True
    assert outcome.is_correct is True
    assert outcome.score == exercise.maximum_score


def test_single_choice_incorrect() -> None:
    correct = _option(True, 0, "a")
    incorrect = _option(False, 1, "b")
    exercise = _exercise(ExerciseType.SINGLE_CHOICE)
    answer = _answer(uuid4(), selected_option_ids=[incorrect.option_id])

    outcome = grade_answer(exercise, [correct, incorrect], answer)

    assert outcome.is_correct is False
    assert outcome.score == 0.0


def test_multiple_choice_requires_exact_match() -> None:
    a = _option(True, 0, "a")
    b = _option(True, 1, "b")
    c = _option(False, 2, "c")
    exercise = _exercise(ExerciseType.MULTIPLE_CHOICE)

    exact_match = _answer(uuid4(), selected_option_ids=[a.option_id, b.option_id])
    partial_match = _answer(uuid4(), selected_option_ids=[a.option_id])

    assert grade_answer(exercise, [a, b, c], exact_match).is_correct is True
    assert grade_answer(exercise, [a, b, c], partial_match).is_correct is False


def test_true_false_grading() -> None:
    true_option = _option(True, 0, "true")
    false_option = _option(False, 1, "false")
    exercise = _exercise(ExerciseType.TRUE_FALSE)

    correct_answer = _answer(uuid4(), selected_option_ids=[true_option.option_id])
    incorrect_answer = _answer(uuid4(), selected_option_ids=[false_option.option_id])

    assert grade_answer(exercise, [true_option, false_option], correct_answer).is_correct is True
    assert grade_answer(exercise, [true_option, false_option], incorrect_answer).is_correct is False


def test_numeric_input_grading_respects_tolerance() -> None:
    exercise = _exercise(
        ExerciseType.NUMERIC_INPUT, configuration={"correct_answer": 18, "tolerance": 1}
    )

    within_tolerance = _answer(uuid4(), numeric_answer=18.5)
    outside_tolerance = _answer(uuid4(), numeric_answer=25.0)

    assert grade_answer(exercise, [], within_tolerance).is_correct is True
    assert grade_answer(exercise, [], outside_tolerance).is_correct is False


def test_numeric_input_requires_correct_answer_in_configuration() -> None:
    exercise = _exercise(ExerciseType.NUMERIC_INPUT, configuration={})
    answer = _answer(uuid4(), numeric_answer=18.0)

    with pytest.raises(InvalidGradingRequestError):
        grade_answer(exercise, [], answer)


def test_ordering_requires_exact_match() -> None:
    step1 = _option(True, 0, "step1")
    step2 = _option(True, 1, "step2")
    step3 = _option(True, 2, "step3")
    exercise = _exercise(ExerciseType.ORDERING)

    correct_order = _answer(
        uuid4(), ordered_option_ids=[step1.option_id, step2.option_id, step3.option_id]
    )
    wrong_order = _answer(
        uuid4(), ordered_option_ids=[step2.option_id, step1.option_id, step3.option_id]
    )

    assert grade_answer(exercise, [step1, step2, step3], correct_order).is_correct is True
    assert grade_answer(exercise, [step1, step2, step3], wrong_order).is_correct is False


def test_text_response_is_not_auto_graded() -> None:
    exercise = _exercise(ExerciseType.TEXT_RESPONSE)
    answer = _answer(uuid4(), text_answer="My reasoning here.")

    outcome = grade_answer(exercise, [], answer)

    assert outcome.graded is False
    assert outcome.is_correct is None
    assert outcome.score is None


def test_scenario_decision_is_not_auto_graded() -> None:
    option = _option(True, 0, "a")
    exercise = _exercise(ExerciseType.SCENARIO_DECISION)
    answer = _answer(uuid4(), selected_option_ids=[option.option_id])

    outcome = grade_answer(exercise, [option], answer)

    assert outcome.graded is False


def test_score_never_exceeds_maximum() -> None:
    correct = _option(True, 0, "a")
    exercise = _exercise(ExerciseType.SINGLE_CHOICE, maximum_score=2.5)
    answer = _answer(uuid4(), selected_option_ids=[correct.option_id])

    outcome = grade_answer(exercise, [correct], answer)

    assert outcome.score is not None and outcome.score <= exercise.maximum_score


def test_grading_package_does_not_import_sqlalchemy() -> None:
    source = inspect.getsource(grading_module)
    assert "sqlalchemy" not in source.lower()


# ---------------------------------------------------------------------------
# Mastery tests
# ---------------------------------------------------------------------------


def test_new_mastery_uses_normalized_score() -> None:
    calculator = DeterministicMasteryCalculator()
    mastery = calculator.update(
        learner_id=uuid4(),
        skill_id=uuid4(),
        previous=None,
        latest_score_normalized=0.7,
        is_correct=True,
        now=NOW,
    )

    assert mastery.mastery_score == pytest.approx(0.7)
    assert mastery.total_attempts == 1
    assert mastery.correct_attempts == 1
    assert mastery.calculation_version == "mastery-v1"


def test_existing_mastery_uses_weighted_update() -> None:
    calculator = DeterministicMasteryCalculator()
    previous = SkillMastery(
        learner_id=uuid4(),
        skill_id=uuid4(),
        mastery_score=0.5,
        total_attempts=1,
        correct_attempts=1,
        calculation_version="mastery-v1",
    )

    updated = calculator.update(
        learner_id=previous.learner_id,
        skill_id=previous.skill_id,
        previous=previous,
        latest_score_normalized=1.0,
        is_correct=True,
        now=NOW,
    )

    expected = 0.8 * 0.5 + 0.2 * 1.0
    assert updated.mastery_score == pytest.approx(expected)
    assert updated.mastery_id == previous.mastery_id


def test_correct_and_total_counts_update() -> None:
    calculator = DeterministicMasteryCalculator()
    previous = SkillMastery(
        learner_id=uuid4(),
        skill_id=uuid4(),
        mastery_score=0.5,
        total_attempts=2,
        correct_attempts=1,
        calculation_version="mastery-v1",
    )

    updated = calculator.update(
        learner_id=previous.learner_id,
        skill_id=previous.skill_id,
        previous=previous,
        latest_score_normalized=1.0,
        is_correct=True,
        now=NOW,
    )

    assert updated.total_attempts == 3
    assert updated.correct_attempts == 2


def test_consecutive_correct_resets_on_failure() -> None:
    calculator = DeterministicMasteryCalculator()
    previous = SkillMastery(
        learner_id=uuid4(),
        skill_id=uuid4(),
        mastery_score=0.7,
        total_attempts=3,
        correct_attempts=3,
        consecutive_correct=3,
        calculation_version="mastery-v1",
    )

    updated = calculator.update(
        learner_id=previous.learner_id,
        skill_id=previous.skill_id,
        previous=previous,
        latest_score_normalized=0.0,
        is_correct=False,
        now=NOW,
    )

    assert updated.consecutive_correct == 0


@pytest.mark.parametrize(
    ("score", "total_attempts", "expected_level"),
    [
        (0.10, 5, MasteryLevel.NOVICE),
        (0.45, 5, MasteryLevel.DEVELOPING),
        (0.70, 5, MasteryLevel.PROFICIENT),
        (0.90, 5, MasteryLevel.MASTERED),
    ],
)
def test_mastery_level_thresholds(
    score: float, total_attempts: int, expected_level: MasteryLevel
) -> None:
    level = mastery_module._mastery_level_for(score, total_attempts)
    assert level == expected_level


def test_mastered_requires_sufficient_evidence() -> None:
    level_with_few_attempts = mastery_module._mastery_level_for(0.95, total_attempts=1)
    level_with_enough_attempts = mastery_module._mastery_level_for(0.95, total_attempts=3)

    assert level_with_few_attempts == MasteryLevel.PROFICIENT
    assert level_with_enough_attempts == MasteryLevel.MASTERED


def test_calculation_version_is_preserved() -> None:
    calculator = DeterministicMasteryCalculator()
    mastery = calculator.update(
        learner_id=uuid4(),
        skill_id=uuid4(),
        previous=None,
        latest_score_normalized=0.5,
        is_correct=True,
        now=NOW,
    )
    assert mastery.calculation_version == calculator.calculation_version == "mastery-v1"


# ---------------------------------------------------------------------------
# Service tests (fakes; no SQLAlchemy/PostgreSQL)
# ---------------------------------------------------------------------------


class FakeLearnerRepository:
    def __init__(self) -> None:
        self.learners: dict[UUID, LearnerProfile] = {}

    async def create(self, learner: LearnerProfile) -> LearnerProfile:
        self.learners[learner.learner_id] = learner
        return learner

    async def get(self, learner_id: UUID) -> LearnerProfile | None:
        return self.learners.get(learner_id)

    async def update(self, learner: LearnerProfile) -> LearnerProfile:
        self.learners[learner.learner_id] = learner
        return learner

    async def set_active(self, learner_id: UUID, active: bool) -> LearnerProfile:
        updated = self.learners[learner_id].model_copy(update={"active": active})
        self.learners[learner_id] = updated
        return updated


class FakeCurriculumRepository:
    def __init__(self) -> None:
        self.skills: dict[UUID, Skill] = {}
        self.paths: dict[UUID, LearningPath] = {}
        self.modules: dict[UUID, LearningModule] = {}
        self.lessons: dict[UUID, Lesson] = {}
        self.exercises: dict[UUID, Exercise] = {}
        self.options: dict[UUID, list[ExerciseOption]] = {}

    async def upsert_skill(self, skill: Skill) -> Skill:
        self.skills[skill.skill_id] = skill
        return skill

    async def get_skill(self, skill_id: UUID) -> Skill | None:
        return self.skills.get(skill_id)

    async def list_skills(self, active_only: bool = True) -> list[Skill]:
        values = list(self.skills.values())
        if active_only:
            values = [s for s in values if s.active]
        return sorted(values, key=lambda s: s.code)

    async def upsert_path(self, path: LearningPath) -> LearningPath:
        self.paths[path.path_id] = path
        return path

    async def list_paths(self, published_only: bool = True) -> list[LearningPath]:
        values = list(self.paths.values())
        if published_only:
            values = [p for p in values if p.published]
        return sorted(values, key=lambda p: p.position)

    async def upsert_module(self, module: LearningModule) -> LearningModule:
        self.modules[module.module_id] = module
        return module

    async def list_modules(self, path_id: UUID) -> list[LearningModule]:
        values = [m for m in self.modules.values() if m.path_id == path_id]
        return sorted(values, key=lambda m: m.position)

    async def upsert_lesson(self, lesson: Lesson) -> Lesson:
        self.lessons[lesson.lesson_id] = lesson
        return lesson

    async def get_lesson(self, lesson_id: UUID) -> Lesson | None:
        return self.lessons.get(lesson_id)

    async def list_lessons(self, module_id: UUID) -> list[Lesson]:
        values = [lesson for lesson in self.lessons.values() if lesson.module_id == module_id]
        return sorted(values, key=lambda lesson: lesson.position)

    async def upsert_exercise(self, exercise: Exercise) -> Exercise:
        self.exercises[exercise.exercise_id] = exercise
        return exercise

    async def get_exercise(self, exercise_id: UUID) -> Exercise | None:
        return self.exercises.get(exercise_id)

    async def list_exercises(self, lesson_id: UUID) -> list[Exercise]:
        values = [ex for ex in self.exercises.values() if ex.lesson_id == lesson_id]
        return sorted(values, key=lambda ex: ex.position)

    async def upsert_options(self, options: list[ExerciseOption]) -> int:
        for option in options:
            bucket = self.options.setdefault(option.exercise_id, [])
            bucket[:] = [o for o in bucket if o.option_id != option.option_id]
            bucket.append(option)
        return len(options)

    async def list_options(self, exercise_id: UUID) -> list[ExerciseOption]:
        return sorted(self.options.get(exercise_id, []), key=lambda o: o.position)


class FakeAttemptRepository:
    def __init__(self) -> None:
        self.attempts: dict[UUID, ExerciseAttempt] = {}
        self.answers: dict[UUID, ExerciseAnswer] = {}

    async def create_attempt(self, attempt: ExerciseAttempt) -> ExerciseAttempt:
        self.attempts[attempt.attempt_id] = attempt
        return attempt

    async def get_attempt(self, attempt_id: UUID) -> ExerciseAttempt | None:
        return self.attempts.get(attempt_id)

    async def save_answer(self, answer: ExerciseAnswer) -> ExerciseAnswer:
        self.answers[answer.answer_id] = answer
        return answer

    async def update_attempt(self, attempt: ExerciseAttempt) -> ExerciseAttempt:
        self.attempts[attempt.attempt_id] = attempt
        return attempt

    async def list_attempts(
        self, learner_id: UUID, exercise_id: UUID | None = None
    ) -> list[ExerciseAttempt]:
        values = [a for a in self.attempts.values() if a.learner_id == learner_id]
        if exercise_id is not None:
            values = [a for a in values if a.exercise_id == exercise_id]
        return sorted(values, key=lambda a: a.started_at)


class FakeMasteryRepository:
    def __init__(self) -> None:
        self.mastery: dict[tuple[UUID, UUID], SkillMastery] = {}

    async def upsert(self, mastery: SkillMastery) -> SkillMastery:
        self.mastery[(mastery.learner_id, mastery.skill_id)] = mastery
        return mastery

    async def get(self, learner_id: UUID, skill_id: UUID) -> SkillMastery | None:
        return self.mastery.get((learner_id, skill_id))

    async def list_for_learner(self, learner_id: UUID) -> list[SkillMastery]:
        return [m for m in self.mastery.values() if m.learner_id == learner_id]


class FailingMasteryRepository(FakeMasteryRepository):
    async def upsert(self, mastery: SkillMastery) -> SkillMastery:
        raise RuntimeError("simulated database failure")


class FakeProgressRepository:
    def __init__(self) -> None:
        self.progress: dict[UUID, UserProgress] = {}

    async def upsert(self, progress: UserProgress) -> UserProgress:
        for existing in self.progress.values():
            if (
                existing.learner_id == progress.learner_id
                and existing.lesson_id == progress.lesson_id
                and progress.lesson_id is not None
            ):
                merged = progress.model_copy(update={"progress_id": existing.progress_id})
                self.progress[existing.progress_id] = merged
                return merged
        self.progress[progress.progress_id] = progress
        return progress

    async def get_lesson_progress(self, learner_id: UUID, lesson_id: UUID) -> UserProgress | None:
        for progress in self.progress.values():
            if progress.learner_id == learner_id and progress.lesson_id == lesson_id:
                return progress
        return None

    async def list_for_learner(self, learner_id: UUID) -> list[UserProgress]:
        return [p for p in self.progress.values() if p.learner_id == learner_id]


class FakeMisconceptionRepository:
    def __init__(self) -> None:
        self.misconceptions: dict[UUID, Misconception] = {}

    async def upsert(self, misconception: Misconception) -> Misconception:
        self.misconceptions[misconception.misconception_id] = misconception
        return misconception

    async def list_active(self, learner_id: UUID) -> list[Misconception]:
        return [
            m
            for m in self.misconceptions.values()
            if m.learner_id == learner_id and m.status == MisconceptionStatus.ACTIVE
        ]

    async def resolve(self, misconception_id: UUID, resolved_at: datetime) -> Misconception:
        updated = self.misconceptions[misconception_id].model_copy(
            update={"status": MisconceptionStatus.RESOLVED, "resolved_at": resolved_at}
        )
        self.misconceptions[misconception_id] = updated
        return updated


class FakeUnitOfWork:
    def __init__(
        self,
        learners: FakeLearnerRepository,
        curriculum: FakeCurriculumRepository,
        attempts: FakeAttemptRepository,
        mastery: FakeMasteryRepository,
        progress: FakeProgressRepository,
        misconceptions: FakeMisconceptionRepository,
    ) -> None:
        self.learners = learners
        self.curriculum = curriculum
        self.attempts = attempts
        self.mastery = mastery
        self.progress = progress
        self.misconceptions = misconceptions
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is not None:
            self.rolled_back = True

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeUnitOfWorkFactory:
    def __init__(self, mastery: FakeMasteryRepository | None = None) -> None:
        self.learners = FakeLearnerRepository()
        self.curriculum = FakeCurriculumRepository()
        self.attempts = FakeAttemptRepository()
        self.mastery = mastery or FakeMasteryRepository()
        self.progress = FakeProgressRepository()
        self.misconceptions = FakeMisconceptionRepository()
        self.instances: list[FakeUnitOfWork] = []

    def __call__(self) -> FakeUnitOfWork:
        uow = FakeUnitOfWork(
            self.learners, self.curriculum, self.attempts, self.mastery, self.progress, self.misconceptions
        )
        self.instances.append(uow)
        return uow


async def _seed_single_choice_lesson(
    factory: FakeUnitOfWorkFactory,
) -> tuple[Skill, Lesson, Exercise, ExerciseOption, ExerciseOption]:
    skill = Skill(
        code="MONEY_BASICS",
        name="Money Basics",
        description="desc",
        category=FinancialSkillCategory.MONEY_BASICS,
        difficulty=DifficultyLevel.BEGINNER,
    )
    await factory.curriculum.upsert_skill(skill)

    lesson = Lesson(
        module_id=uuid4(),
        code="what-money-is-for",
        title="What Money Is For",
        summary="summary",
        content_markdown="# content",
        difficulty=DifficultyLevel.BEGINNER,
        status=LessonStatus.PUBLISHED,
        position=0,
        estimated_minutes=15,
        primary_skill_id=skill.skill_id,
    )
    await factory.curriculum.upsert_lesson(lesson)

    exercise = Exercise(
        lesson_id=lesson.lesson_id,
        exercise_type=ExerciseType.SINGLE_CHOICE,
        prompt="prompt",
        explanation="explanation",
        difficulty=DifficultyLevel.BEGINNER,
        position=0,
        skill_ids=[skill.skill_id],
        maximum_score=1.0,
        passing_score=1.0,
    )
    await factory.curriculum.upsert_exercise(exercise)

    correct_option = ExerciseOption(
        exercise_id=exercise.exercise_id, option_key="a", content="Correct", position=0, is_correct=True
    )
    incorrect_option = ExerciseOption(
        exercise_id=exercise.exercise_id, option_key="b", content="Incorrect", position=1, is_correct=False
    )
    await factory.curriculum.upsert_options([correct_option, incorrect_option])

    return skill, lesson, exercise, correct_option, incorrect_option


async def test_learner_creation_defaults_to_english() -> None:
    factory = FakeUnitOfWorkFactory()
    service = LearningService(unit_of_work_factory=factory)

    learner = await service.create_learner(display_name="Amit")

    assert learner.preferred_language == "en"
    assert factory.learners.learners[learner.learner_id] == learner


async def test_lesson_retrieval_with_exercises() -> None:
    factory = FakeUnitOfWorkFactory()
    service = LearningService(unit_of_work_factory=factory)
    _, lesson, exercise, correct_option, incorrect_option = await _seed_single_choice_lesson(factory)

    result = await service.get_lesson_with_exercises(lesson.lesson_id)

    assert result.lesson.lesson_id == lesson.lesson_id
    assert len(result.exercises) == 1
    assert {opt.option_id for opt in result.options_by_exercise[exercise.exercise_id]} == {
        correct_option.option_id,
        incorrect_option.option_id,
    }


async def test_attempt_numbering_increments() -> None:
    factory = FakeUnitOfWorkFactory()
    service = LearningService(unit_of_work_factory=factory)
    _, _, exercise, _, _ = await _seed_single_choice_lesson(factory)
    learner_id = uuid4()

    first = await service.start_exercise_attempt(learner_id=learner_id, exercise_id=exercise.exercise_id)
    second = await service.start_exercise_attempt(learner_id=learner_id, exercise_id=exercise.exercise_id)

    assert first.attempt_number == 1
    assert second.attempt_number == 2


async def test_submission_persists_answer_and_attempt_atomically() -> None:
    factory = FakeUnitOfWorkFactory()
    service = LearningService(unit_of_work_factory=factory)
    _, _, exercise, correct_option, _ = await _seed_single_choice_lesson(factory)
    learner_id = uuid4()
    attempt = await service.start_exercise_attempt(learner_id=learner_id, exercise_id=exercise.exercise_id)

    answer = ExerciseAnswer(attempt_id=attempt.attempt_id, selected_option_ids=[correct_option.option_id])
    result = await service.submit_answer(attempt_id=attempt.attempt_id, answer=answer)

    assert result.attempt.status == AttemptStatus.GRADED
    assert result.attempt.is_correct is True
    assert result.answer.attempt_id == attempt.attempt_id
    assert factory.attempts.attempts[attempt.attempt_id].status == AttemptStatus.GRADED


async def test_submission_updates_mastery() -> None:
    factory = FakeUnitOfWorkFactory()
    service = LearningService(unit_of_work_factory=factory)
    skill, _, exercise, correct_option, _ = await _seed_single_choice_lesson(factory)
    learner_id = uuid4()
    attempt = await service.start_exercise_attempt(learner_id=learner_id, exercise_id=exercise.exercise_id)

    answer = ExerciseAnswer(attempt_id=attempt.attempt_id, selected_option_ids=[correct_option.option_id])
    result = await service.submit_answer(attempt_id=attempt.attempt_id, answer=answer)

    assert len(result.updated_mastery) == 1
    assert result.updated_mastery[0].skill_id == skill.skill_id
    assert factory.mastery.mastery[(learner_id, skill.skill_id)].total_attempts == 1


async def test_submission_updates_progress() -> None:
    factory = FakeUnitOfWorkFactory()
    service = LearningService(unit_of_work_factory=factory)
    _, lesson, exercise, correct_option, _ = await _seed_single_choice_lesson(factory)
    learner_id = uuid4()
    attempt = await service.start_exercise_attempt(learner_id=learner_id, exercise_id=exercise.exercise_id)

    answer = ExerciseAnswer(attempt_id=attempt.attempt_id, selected_option_ids=[correct_option.option_id])
    result = await service.submit_answer(attempt_id=attempt.attempt_id, answer=answer)

    assert result.updated_progress is not None
    assert result.updated_progress.lesson_id == lesson.lesson_id
    assert result.updated_progress.status == ProgressStatus.COMPLETED
    assert result.updated_progress.completion_percentage == pytest.approx(100.0)


async def test_ungraded_exercise_type_does_not_update_mastery_or_progress() -> None:
    factory = FakeUnitOfWorkFactory()
    service = LearningService(unit_of_work_factory=factory)
    skill, lesson, exercise, correct_option, _ = await _seed_single_choice_lesson(factory)

    text_exercise = Exercise(
        lesson_id=lesson.lesson_id,
        exercise_type=ExerciseType.TEXT_RESPONSE,
        prompt="Explain diversification in your own words.",
        explanation="No single correct wording.",
        difficulty=DifficultyLevel.BEGINNER,
        position=1,
        skill_ids=[skill.skill_id],
        maximum_score=1.0,
        passing_score=1.0,
    )
    await factory.curriculum.upsert_exercise(text_exercise)
    learner_id = uuid4()
    attempt = await service.start_exercise_attempt(
        learner_id=learner_id, exercise_id=text_exercise.exercise_id
    )

    answer = ExerciseAnswer(attempt_id=attempt.attempt_id, text_answer="My own explanation.")
    result = await service.submit_answer(attempt_id=attempt.attempt_id, answer=answer)

    assert result.attempt.status == AttemptStatus.SUBMITTED
    assert result.updated_mastery == []
    assert result.updated_progress is None


async def test_failure_rolls_back_the_complete_transaction() -> None:
    factory = FakeUnitOfWorkFactory(mastery=FailingMasteryRepository())
    service = LearningService(unit_of_work_factory=factory)
    _, _, exercise, correct_option, _ = await _seed_single_choice_lesson(factory)
    learner_id = uuid4()
    attempt = await service.start_exercise_attempt(learner_id=learner_id, exercise_id=exercise.exercise_id)

    answer = ExerciseAnswer(attempt_id=attempt.attempt_id, selected_option_ids=[correct_option.option_id])

    with pytest.raises(RuntimeError):
        await service.submit_answer(attempt_id=attempt.attempt_id, answer=answer)

    submission_uow = factory.instances[-1]
    assert submission_uow.committed is False
    assert submission_uow.rolled_back is True


async def test_application_service_uses_protocols_via_fakes() -> None:
    """Fakes satisfy the Protocols structurally - the service never checks concrete types."""
    factory = FakeUnitOfWorkFactory()
    service = LearningService(unit_of_work_factory=factory)
    learner = await service.create_learner(display_name="Structural Typing Check")
    assert learner.display_name == "Structural Typing Check"


def _imported_root_modules(module: object) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    return {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }


def test_application_learning_package_does_not_import_sqlalchemy() -> None:
    for module in (service_module, grading_module, mastery_module):
        imported = _imported_root_modules(module)
        assert "sqlalchemy" not in imported
        assert "asyncpg" not in imported


def test_domain_learning_package_does_not_import_sqlalchemy() -> None:
    for module in (learning_enums_module, learning_models_module):
        imported = _imported_root_modules(module)
        forbidden = {"sqlalchemy", "asyncpg", "pandas", "yfinance", "fastapi"}
        assert imported.isdisjoint(forbidden), f"{module.__name__} imports {imported & forbidden}"
