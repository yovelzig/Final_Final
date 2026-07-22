"""Enumerations for the FinQuest personalized learning orchestrator
(Phase 12: LangGraph-based interactive learning coach).

This module has no knowledge of any infrastructure (databases, queues,
LangGraph, HTTP frameworks, orchestration engines, etc.).
"""

from enum import StrEnum


class LearningOrchestratorThreadStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class LearningOrchestratorRunStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    WAITING_FOR_LEARNER = "WAITING_FOR_LEARNER"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


#: Statuses from which a run will never transition again.
TERMINAL_RUN_STATUSES: frozenset[LearningOrchestratorRunStatus] = frozenset(
    {
        LearningOrchestratorRunStatus.SUCCEEDED,
        LearningOrchestratorRunStatus.FAILED,
        LearningOrchestratorRunStatus.CANCELLED,
        LearningOrchestratorRunStatus.EXPIRED,
    }
)


class LearningIntent(StrEnum):
    EXPLAIN_CONCEPT = "EXPLAIN_CONCEPT"
    LESSON_HELP = "LESSON_HELP"
    EXERCISE_HELP = "EXERCISE_HELP"
    REVIEW_PROGRESS = "REVIEW_PROGRESS"
    RECOMMEND_NEXT_LEARNING_ACTIVITY = "RECOMMEND_NEXT_LEARNING_ACTIVITY"
    START_DAILY_PRACTICE = "START_DAILY_PRACTICE"
    START_DIAGNOSTIC = "START_DIAGNOSTIC"
    SCENARIO_HELP_BEFORE_DECISION = "SCENARIO_HELP_BEFORE_DECISION"
    SCENARIO_HELP_AFTER_REVEAL = "SCENARIO_HELP_AFTER_REVEAL"
    PORTFOLIO_EXPLANATION = "PORTFOLIO_EXPLANATION"
    GENERAL_TUTOR_CHAT = "GENERAL_TUTOR_CHAT"
    UNKNOWN = "UNKNOWN"


class LearningOrchestratorRoute(StrEnum):
    GROUNDED_EXPLANATION = "GROUNDED_EXPLANATION"
    LESSON_TUTOR = "LESSON_TUTOR"
    EXERCISE_TUTOR = "EXERCISE_TUTOR"
    PROGRESS_REFLECTION = "PROGRESS_REFLECTION"
    ADAPTIVE_RECOMMENDATION = "ADAPTIVE_RECOMMENDATION"
    PRACTICE_ACTION = "PRACTICE_ACTION"
    DIAGNOSTIC_ACTION = "DIAGNOSTIC_ACTION"
    SCENARIO_BEFORE_TUTOR = "SCENARIO_BEFORE_TUTOR"
    SCENARIO_AFTER_TUTOR = "SCENARIO_AFTER_TUTOR"
    PORTFOLIO_TUTOR = "PORTFOLIO_TUTOR"
    REFUSAL = "REFUSAL"
    FALLBACK = "FALLBACK"


class LearningActionType(StrEnum):
    START_ADAPTIVE_SESSION = "START_ADAPTIVE_SESSION"
    START_DIAGNOSTIC_ASSESSMENT = "START_DIAGNOSTIC_ASSESSMENT"
    OPEN_LESSON = "OPEN_LESSON"
    OPEN_SCENARIO = "OPEN_SCENARIO"
    OPEN_PORTFOLIO = "OPEN_PORTFOLIO"
    CREATE_TUTOR_CONVERSATION = "CREATE_TUTOR_CONVERSATION"


#: Action types that mutate FinQuest state and therefore require explicit
#: learner approval via a LangGraph interrupt before executing.
APPROVAL_REQUIRED_ACTION_TYPES: frozenset[LearningActionType] = frozenset(
    {
        LearningActionType.START_ADAPTIVE_SESSION,
        LearningActionType.START_DIAGNOSTIC_ASSESSMENT,
        LearningActionType.CREATE_TUTOR_CONVERSATION,
    }
)

#: Navigation-only action types - never a mutation, never require approval.
NAVIGATION_ONLY_ACTION_TYPES: frozenset[LearningActionType] = frozenset(
    {
        LearningActionType.OPEN_LESSON,
        LearningActionType.OPEN_SCENARIO,
        LearningActionType.OPEN_PORTFOLIO,
    }
)


class LearningActionProposalStatus(StrEnum):
    PROPOSED = "PROPOSED"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EDITED = "EDITED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


TERMINAL_ACTION_PROPOSAL_STATUSES: frozenset[LearningActionProposalStatus] = frozenset(
    {
        LearningActionProposalStatus.REJECTED,
        LearningActionProposalStatus.SUCCEEDED,
        LearningActionProposalStatus.FAILED,
        LearningActionProposalStatus.EXPIRED,
    }
)


class LearnerApprovalDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    EDIT = "EDIT"


class LearningOrchestratorEventType(StrEnum):
    RUN_CREATED = "RUN_CREATED"
    RUN_STARTED = "RUN_STARTED"
    CONTEXT_LOADING = "CONTEXT_LOADING"
    INTENT_CLASSIFIED = "INTENT_CLASSIFIED"
    ROUTE_SELECTED = "ROUTE_SELECTED"
    RETRIEVAL_STARTED = "RETRIEVAL_STARTED"
    RETRIEVAL_COMPLETED = "RETRIEVAL_COMPLETED"
    TUTOR_RESPONSE_STARTED = "TUTOR_RESPONSE_STARTED"
    TUTOR_RESPONSE_COMPLETED = "TUTOR_RESPONSE_COMPLETED"
    ACTION_PROPOSED = "ACTION_PROPOSED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    ACTION_APPROVED = "ACTION_APPROVED"
    ACTION_REJECTED = "ACTION_REJECTED"
    ACTION_EXECUTING = "ACTION_EXECUTING"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    RUN_COMPLETED = "RUN_COMPLETED"
    RUN_FAILED = "RUN_FAILED"
    RUN_CANCELLED = "RUN_CANCELLED"


class IntentClassificationMethod(StrEnum):
    RULE_BASED = "RULE_BASED"
    MODEL_ASSISTED = "MODEL_ASSISTED"
    FALLBACK = "FALLBACK"
