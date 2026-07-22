"""Deterministic, explicit exercise grading rules.

No LLM, no machine learning: every rule here is a plain, testable
function. `TEXT_RESPONSE` and `SCENARIO_DECISION` are intentionally
never auto-graded - there is no deterministic rubric for them yet.
"""

from __future__ import annotations

from typing import NamedTuple

from stock_research_core.application.exceptions import InvalidGradingRequestError
from stock_research_core.domain.learning.enums import ExerciseType
from stock_research_core.domain.learning.models import Exercise, ExerciseAnswer, ExerciseOption

_AUTO_GRADED_TYPES = frozenset(
    {
        ExerciseType.SINGLE_CHOICE,
        ExerciseType.MULTIPLE_CHOICE,
        ExerciseType.TRUE_FALSE,
        ExerciseType.NUMERIC_INPUT,
        ExerciseType.ORDERING,
    }
)

_DEFAULT_NUMERIC_TOLERANCE = 0.0


class GradingOutcome(NamedTuple):
    """The result of attempting to grade a submitted answer."""

    graded: bool
    is_correct: bool | None
    score: float | None


def is_auto_gradable(exercise_type: ExerciseType) -> bool:
    return exercise_type in _AUTO_GRADED_TYPES


def grade_answer(
    exercise: Exercise, options: list[ExerciseOption], answer: ExerciseAnswer
) -> GradingOutcome:
    """Grade `answer` against `exercise`, or report it cannot be auto-graded.

    `options` is only consulted for option-based exercise types
    (SINGLE_CHOICE, TRUE_FALSE, MULTIPLE_CHOICE, ORDERING); it is
    ignored for NUMERIC_INPUT.
    """
    if not is_auto_gradable(exercise.exercise_type):
        return GradingOutcome(graded=False, is_correct=None, score=None)

    if exercise.exercise_type in (ExerciseType.SINGLE_CHOICE, ExerciseType.TRUE_FALSE):
        is_correct = _grade_single_choice(options, answer)
    elif exercise.exercise_type == ExerciseType.MULTIPLE_CHOICE:
        is_correct = _grade_multiple_choice(options, answer)
    elif exercise.exercise_type == ExerciseType.NUMERIC_INPUT:
        is_correct = _grade_numeric_input(exercise, answer)
    elif exercise.exercise_type == ExerciseType.ORDERING:
        is_correct = _grade_ordering(options, answer)
    else:  # pragma: no cover - guarded by is_auto_gradable above
        raise InvalidGradingRequestError(
            f"No grading rule implemented for exercise type '{exercise.exercise_type}'."
        )

    score = exercise.maximum_score if is_correct else 0.0
    return GradingOutcome(graded=True, is_correct=is_correct, score=score)


def _correct_option_ids(options: list[ExerciseOption]) -> set:
    return {option.option_id for option in options if option.is_correct}


def _grade_single_choice(options: list[ExerciseOption], answer: ExerciseAnswer) -> bool:
    if len(answer.selected_option_ids) != 1:
        raise InvalidGradingRequestError(
            "A single-choice or true/false answer must select exactly one option."
        )
    correct_ids = _correct_option_ids(options)
    if len(correct_ids) != 1:
        raise InvalidGradingRequestError(
            "A single-choice or true/false exercise must have exactly one correct option."
        )
    return set(answer.selected_option_ids) == correct_ids


def _grade_multiple_choice(options: list[ExerciseOption], answer: ExerciseAnswer) -> bool:
    if not answer.selected_option_ids:
        raise InvalidGradingRequestError(
            "A multiple-choice answer must select at least one option."
        )
    correct_ids = _correct_option_ids(options)
    return set(answer.selected_option_ids) == correct_ids


def _grade_numeric_input(exercise: Exercise, answer: ExerciseAnswer) -> bool:
    if answer.numeric_answer is None:
        raise InvalidGradingRequestError("A numeric-input answer must supply numeric_answer.")

    configuration = exercise.configuration
    if "correct_answer" not in configuration:
        raise InvalidGradingRequestError(
            "Exercise configuration is missing required key 'correct_answer' for grading."
        )
    correct_answer = configuration["correct_answer"]
    if not isinstance(correct_answer, (int, float)) or isinstance(correct_answer, bool):
        raise InvalidGradingRequestError(
            "Exercise configuration 'correct_answer' must be numeric."
        )

    tolerance = configuration.get("tolerance", _DEFAULT_NUMERIC_TOLERANCE)
    if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool) or tolerance < 0:
        raise InvalidGradingRequestError(
            "Exercise configuration 'tolerance' must be a non-negative number."
        )

    return abs(answer.numeric_answer - float(correct_answer)) <= float(tolerance)


def _grade_ordering(options: list[ExerciseOption], answer: ExerciseAnswer) -> bool:
    if not answer.ordered_option_ids:
        raise InvalidGradingRequestError("An ordering answer must supply ordered_option_ids.")
    correct_order = [option.option_id for option in sorted(options, key=lambda o: o.position)]
    return answer.ordered_option_ids == correct_order
