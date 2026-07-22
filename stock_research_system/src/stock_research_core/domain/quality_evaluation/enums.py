"""Enumerations for the FinQuest quality-evaluation platform (Phase 13).

This module has no knowledge of any infrastructure (databases, RAGAS,
queues, HTTP frameworks, etc.) - the same rule every other `domain/*`
package follows.
"""

from enum import StrEnum


class QualityEvaluationSuiteType(StrEnum):
    RAG_SINGLE_TURN = "RAG_SINGLE_TURN"
    COACH_MULTI_TURN = "COACH_MULTI_TURN"
    SAFETY = "SAFETY"
    SCENARIO_POINT_IN_TIME = "SCENARIO_POINT_IN_TIME"
    PORTFOLIO_EDUCATION = "PORTFOLIO_EDUCATION"
    LEARNING_OUTCOME = "LEARNING_OUTCOME"
    MIXED = "MIXED"


class QualityEvaluationMode(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    RAGAS = "RAGAS"
    HYBRID = "HYBRID"


class QualityEvaluationRunStatus(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIALLY_SUCCEEDED = "PARTIALLY_SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


#: Statuses from which a run will never transition again.
TERMINAL_QUALITY_EVALUATION_RUN_STATUSES: frozenset[QualityEvaluationRunStatus] = frozenset(
    {
        QualityEvaluationRunStatus.SUCCEEDED,
        QualityEvaluationRunStatus.PARTIALLY_SUCCEEDED,
        QualityEvaluationRunStatus.FAILED,
        QualityEvaluationRunStatus.CANCELLED,
    }
)


class QualityEvaluationCaseStatus(StrEnum):
    DRAFT = "DRAFT"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    ARCHIVED = "ARCHIVED"


class QualityMetricType(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    RAGAS = "RAGAS"
    LEARNING_OUTCOME = "LEARNING_OUTCOME"
    SAFETY_GATE = "SAFETY_GATE"


class QualityGateStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"


class EvaluationComparisonResult(StrEnum):
    IMPROVED = "IMPROVED"
    UNCHANGED = "UNCHANGED"
    REGRESSED = "REGRESSED"
    NOT_COMPARABLE = "NOT_COMPARABLE"


class LearningOutcomeMetricType(StrEnum):
    MASTERY_GAIN = "MASTERY_GAIN"
    NORMALIZED_LEARNING_GAIN = "NORMALIZED_LEARNING_GAIN"
    RETENTION_RATIO = "RETENTION_RATIO"
    MISCONCEPTION_RECURRENCE_RATE = "MISCONCEPTION_RECURRENCE_RATE"
    CONFIDENCE_BRIER_SCORE = "CONFIDENCE_BRIER_SCORE"
    CONFIDENCE_CALIBRATION_ERROR = "CONFIDENCE_CALIBRATION_ERROR"
    SCENARIO_DECISION_QUALITY_GAIN = "SCENARIO_DECISION_QUALITY_GAIN"
    RISK_IDENTIFICATION_GAIN = "RISK_IDENTIFICATION_GAIN"
    LESSON_COMPLETION_RATE = "LESSON_COMPLETION_RATE"
    PRACTICE_COMPLETION_RATE = "PRACTICE_COMPLETION_RATE"


class EvaluationCaseContextType(StrEnum):
    GENERAL_RAG = "GENERAL_RAG"
    LESSON = "LESSON"
    EXERCISE_BEFORE_SUBMISSION = "EXERCISE_BEFORE_SUBMISSION"
    EXERCISE_AFTER_SUBMISSION = "EXERCISE_AFTER_SUBMISSION"
    SCENARIO_BEFORE_REVEAL = "SCENARIO_BEFORE_REVEAL"
    SCENARIO_AFTER_REVEAL = "SCENARIO_AFTER_REVEAL"
    PORTFOLIO = "PORTFOLIO"
    COACH = "COACH"


#: Identity level a retrieval metric (Hit@K/MRR/Precision@K/Recall@K) was
#: computed against - recorded alongside every such `QualityMetricResult`
#: (spec section 11: "Record which identity level was used").
class EvaluationEvidenceIdentity(StrEnum):
    CHUNK = "CHUNK"
    DOCUMENT = "DOCUMENT"
