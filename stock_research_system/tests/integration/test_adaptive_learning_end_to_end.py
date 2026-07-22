"""PostgreSQL end-to-end integration tests for the adaptive learning engine.

Exercises the real `AdaptiveLearningService`, `LearningService`, and
`AdaptiveLearningOrchestrator` together against the actual test
database - the full recommend -> start -> grade -> record-outcome and
diagnostic flows, not just individual repositories.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.adaptive_learning.orchestrator import (
    AdaptiveLearningOrchestrator,
)
from stock_research_core.application.adaptive_learning.policies import (
    DeterministicReviewSchedulingPolicy,
    RuleBasedAdaptivePolicy,
    RuleBasedDiagnosticPolicy,
    RuleBasedDifficultyPolicy,
)
from stock_research_core.application.adaptive_learning.service import AdaptiveLearningService
from stock_research_core.application.exceptions import LearningSessionNotFoundError
from stock_research_core.application.learning.service import LearningService
from stock_research_core.domain.adaptive_learning.enums import RecommendationType
from stock_research_core.domain.adaptive_learning.models import ExerciseAdaptiveProfile
from stock_research_core.domain.learning.enums import (
    DifficultyLevel,
    ExerciseType,
    FinancialSkillCategory,
    LessonStatus,
)
from stock_research_core.domain.learning.models import (
    Exercise,
    ExerciseAnswer,
    ExerciseOption,
    Lesson,
    LearningModule,
    LearningPath,
    Skill,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _make_adaptive_service(uow_factory) -> AdaptiveLearningService:
    return AdaptiveLearningService(
        unit_of_work_factory=uow_factory,
        adaptive_policy=RuleBasedAdaptivePolicy(),
        difficulty_policy=RuleBasedDifficultyPolicy(),
        review_policy=DeterministicReviewSchedulingPolicy(),
        diagnostic_policy=RuleBasedDiagnosticPolicy(),
        clock=lambda: NOW,
    )


async def _seed_single_choice_lesson(uow_factory):
    skill = Skill(
        code=f"MONEY_BASICS_{uuid4().hex[:8].upper()}",
        name="Money Basics",
        description="desc",
        category=FinancialSkillCategory.MONEY_BASICS,
        difficulty=DifficultyLevel.BEGINNER,
    )
    async with uow_factory() as uow:
        stored_skill = await uow.curriculum.upsert_skill(skill)
        path = await uow.curriculum.upsert_path(
            LearningPath(
                code=f"path-{uuid4().hex[:8]}", title="Path", description="d",
                difficulty=DifficultyLevel.BEGINNER, position=0, estimated_minutes=10, published=True,
            )
        )
        module = await uow.curriculum.upsert_module(
            LearningModule(
                path_id=path.path_id, code="mod", title="Module", description="d",
                position=0, estimated_minutes=10, published=True,
            )
        )
        lesson = await uow.curriculum.upsert_lesson(
            Lesson(
                module_id=module.module_id, code="lesson", title="Lesson", summary="s",
                content_markdown="# c", difficulty=DifficultyLevel.BEGINNER,
                status=LessonStatus.PUBLISHED, position=0, estimated_minutes=10,
                primary_skill_id=stored_skill.skill_id,
            )
        )
        exercise = await uow.curriculum.upsert_exercise(
            Exercise(
                lesson_id=lesson.lesson_id, exercise_type=ExerciseType.SINGLE_CHOICE,
                prompt="Which of these is a medium of exchange?", explanation="Money is.",
                difficulty=DifficultyLevel.BEGINNER, position=0, skill_ids=[stored_skill.skill_id],
                maximum_score=1.0, passing_score=1.0,
            )
        )
        correct_option = ExerciseOption(
            exercise_id=exercise.exercise_id, option_key="a", content="Money", position=0, is_correct=True
        )
        incorrect_option = ExerciseOption(
            exercise_id=exercise.exercise_id, option_key="b", content="A rock", position=1, is_correct=False
        )
        await uow.curriculum.upsert_options([correct_option, incorrect_option])
        await uow.adaptive_profiles.upsert(
            ExerciseAdaptiveProfile(
                exercise_id=exercise.exercise_id, base_difficulty_score=0.5, estimated_seconds=45,
                diagnostic_eligible=True, review_eligible=True,
            )
        )
        await uow.commit()
    return stored_skill, exercise, correct_option


async def test_full_recommendation_and_grading_flow_end_to_end(uow_factory) -> None:
    skill, exercise, correct_option = await _seed_single_choice_lesson(uow_factory)
    learning_service = LearningService(unit_of_work_factory=uow_factory)
    adaptive_service = _make_adaptive_service(uow_factory)
    orchestrator = AdaptiveLearningOrchestrator(learning_service, adaptive_service)

    learner = await learning_service.create_learner(display_name="End To End Learner")
    session = await adaptive_service.start_session(learner_id=learner.learner_id)

    recommendation = await adaptive_service.recommend_next(
        learner_id=learner.learner_id, session_id=session.session_id
    )
    assert recommendation.decision.recommended_exercise_id == exercise.exercise_id

    await adaptive_service.accept_recommendation(decision_id=recommendation.decision.decision_id)
    attempt = await adaptive_service.start_recommended_exercise(
        decision_id=recommendation.decision.decision_id
    )

    answer = ExerciseAnswer(attempt_id=attempt.attempt_id, selected_option_ids=[correct_option.option_id])
    summary = await orchestrator.submit_recommended_answer(
        decision_id=recommendation.decision.decision_id, answer=answer
    )

    assert summary.session.completed_item_count == 1
    assert summary.session.correct_item_count == 1
    assert len(summary.reviews_scheduled) == 1

    async with uow_factory() as uow:
        schedule = await uow.review_schedules.get(learner.learner_id, skill.skill_id)
    assert schedule is not None
    assert schedule.review_interval_days >= 1


async def test_repeated_recommendation_respects_cooldown(uow_factory) -> None:
    skill, exercise, correct_option = await _seed_single_choice_lesson(uow_factory)
    learning_service = LearningService(unit_of_work_factory=uow_factory)
    adaptive_service = _make_adaptive_service(uow_factory)
    orchestrator = AdaptiveLearningOrchestrator(learning_service, adaptive_service)

    learner = await learning_service.create_learner(display_name="Cooldown Learner")
    session = await adaptive_service.start_session(learner_id=learner.learner_id)

    recommendation = await adaptive_service.recommend_next(
        learner_id=learner.learner_id, session_id=session.session_id
    )
    attempt = await adaptive_service.start_recommended_exercise(
        decision_id=recommendation.decision.decision_id
    )
    answer = ExerciseAnswer(attempt_id=attempt.attempt_id, selected_option_ids=[correct_option.option_id])
    await orchestrator.submit_recommended_answer(
        decision_id=recommendation.decision.decision_id, answer=answer
    )

    # The only eligible exercise was just completed - it must not be
    # recommended again immediately (no other candidate exists yet).
    second_recommendation = await adaptive_service.recommend_next(
        learner_id=learner.learner_id, session_id=session.session_id
    )
    assert second_recommendation.decision.recommendation_type == RecommendationType.NO_ELIGIBLE_CONTENT


async def test_full_diagnostic_flow_end_to_end(uow_factory) -> None:
    skill, exercise, correct_option = await _seed_single_choice_lesson(uow_factory)
    learning_service = LearningService(unit_of_work_factory=uow_factory)
    adaptive_service = _make_adaptive_service(uow_factory)

    learner = await learning_service.create_learner(display_name="Diagnostic Learner")

    summary = await adaptive_service.start_diagnostic(
        learner_id=learner.learner_id, skill_ids=[skill.skill_id], maximum_items=5
    )
    assert len(summary.items) == 1
    item = summary.items[0]

    attempt = await adaptive_service.start_diagnostic_item(
        assessment_id=summary.assessment.assessment_id, item_id=item.item_id
    )
    answer = ExerciseAnswer(attempt_id=attempt.attempt_id, selected_option_ids=[correct_option.option_id])
    result = await learning_service.submit_answer(attempt_id=attempt.attempt_id, answer=answer)

    await adaptive_service.record_diagnostic_result(
        assessment_id=summary.assessment.assessment_id, item_id=item.item_id, learning_activity_result=result
    )
    final_summary = await adaptive_service.complete_diagnostic(assessment_id=summary.assessment.assessment_id)

    assert final_summary.assessment.status.value == "COMPLETED"
    assert final_summary.skill_scores[skill.skill_id] == 1.0

    async with uow_factory() as uow:
        mastery = await uow.mastery.get(learner.learner_id, skill.skill_id)
    assert mastery is not None
    assert mastery.mastery_score == 1.0


async def test_recommend_next_rolls_back_on_missing_session(uow_factory) -> None:
    _skill, _exercise, _option = await _seed_single_choice_lesson(uow_factory)
    learning_service = LearningService(unit_of_work_factory=uow_factory)
    adaptive_service = _make_adaptive_service(uow_factory)
    learner = await learning_service.create_learner(display_name="Rollback Learner")

    with pytest.raises(LearningSessionNotFoundError):
        await adaptive_service.recommend_next(learner_id=learner.learner_id, session_id=uuid4())

    async with uow_factory() as uow:
        decisions = await uow.adaptive_decisions.list_recent_decisions(learner.learner_id, limit=10)
    assert decisions == []
