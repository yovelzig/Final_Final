"""SQLAlchemy ORM models. Imported eagerly so relationships resolve and
`Base.metadata` is complete for Alembic autogeneration.

These classes are infrastructure-internal: never return them outside
this layer. Repositories map them to/from domain models.
"""

from stock_research_core.infrastructure.database.orm.adaptive_decision import (
    AdaptiveDecisionORM,
    AdaptiveDecisionReasonORM,
    AdaptiveDecisionTargetSkillORM,
)
from stock_research_core.infrastructure.database.orm.diagnostic_assessment import (
    DiagnosticAssessmentORM,
    DiagnosticAssessmentSkillORM,
)
from stock_research_core.infrastructure.database.orm.diagnostic_assessment_item import (
    DiagnosticAssessmentItemORM,
    DiagnosticItemSkillORM,
)
from stock_research_core.infrastructure.database.orm.exercise import (
    ExerciseORM,
    ExerciseSkillORM,
)
from stock_research_core.infrastructure.database.orm.exercise_adaptive_profile import (
    ExerciseAdaptiveProfileORM,
)
from stock_research_core.infrastructure.database.orm.exercise_answer import (
    ExerciseAnswerORM,
    ExerciseAnswerOrderedOptionORM,
    ExerciseAnswerSelectedOptionORM,
)
from stock_research_core.infrastructure.database.orm.exercise_attempt import ExerciseAttemptORM
from stock_research_core.infrastructure.database.orm.exercise_option import ExerciseOptionORM
from stock_research_core.infrastructure.database.orm.historical_market_scenario import (
    HistoricalMarketScenarioORM,
    HistoricalMarketScenarioPrimarySkillORM,
    HistoricalMarketScenarioSecondarySkillORM,
)
from stock_research_core.infrastructure.database.orm.ingestion_run import (
    MarketDataIngestionRunORM,
)
from stock_research_core.infrastructure.database.orm.learner_profile import LearnerProfileORM
from stock_research_core.infrastructure.database.orm.learning_module import LearningModuleORM
from stock_research_core.infrastructure.database.orm.learning_path import LearningPathORM
from stock_research_core.infrastructure.database.orm.learning_session import LearningSessionORM
from stock_research_core.infrastructure.database.orm.learning_session_activity import (
    LearningSessionActivityORM,
)
from stock_research_core.infrastructure.database.orm.lesson import (
    LessonORM,
    LessonSecondarySkillORM,
)
from stock_research_core.infrastructure.database.orm.market_bar import MarketBarORM
from stock_research_core.infrastructure.database.orm.misconception import (
    MisconceptionEvidenceAttemptORM,
    MisconceptionORM,
)
from stock_research_core.infrastructure.database.orm.portfolio_decision_journal import (
    PortfolioDecisionJournalEntryORM,
    PortfolioJournalAssumptionORM,
    PortfolioJournalInformationItemORM,
    PortfolioJournalRiskTagORM,
)
from stock_research_core.infrastructure.database.orm.portfolio_holding import PortfolioHoldingORM
from stock_research_core.infrastructure.database.orm.portfolio_position_valuation import (
    PortfolioPositionValuationORM,
)
from stock_research_core.infrastructure.database.orm.portfolio_risk_assessment import (
    PortfolioRiskAssessmentORM,
    PortfolioRiskFeedbackCodeORM,
    PortfolioRiskSkillORM,
)
from stock_research_core.infrastructure.database.orm.portfolio_transaction import (
    PortfolioTransactionORM,
)
from stock_research_core.infrastructure.database.orm.portfolio_valuation_run import (
    PortfolioValuationRunORM,
)
from stock_research_core.infrastructure.database.orm.portfolio_valuation_snapshot import (
    PortfolioValuationSnapshotORM,
)
from stock_research_core.infrastructure.database.orm.quality_issue import (
    MarketDataQualityIssueORM,
)
from stock_research_core.infrastructure.database.orm.scenario_generation_run import (
    ScenarioGenerationRunORM,
)
from stock_research_core.infrastructure.database.orm.scenario_option_rubric import (
    ScenarioOptionRubricFeedbackCodeORM,
    ScenarioOptionRubricORM,
)
from stock_research_core.infrastructure.database.orm.scenario_outcome import ScenarioOutcomeORM
from stock_research_core.infrastructure.database.orm.scenario_security import ScenarioSecurityORM
from stock_research_core.infrastructure.database.orm.scenario_submission import (
    ScenarioSubmissionFeedbackCodeORM,
    ScenarioSubmissionORM,
)
from stock_research_core.infrastructure.database.orm.security import SecurityORM
from stock_research_core.infrastructure.database.orm.skill import (
    FinancialSkillORM,
    SkillPrerequisiteORM,
)
from stock_research_core.infrastructure.database.orm.skill_mastery import SkillMasteryORM
from stock_research_core.infrastructure.database.orm.skill_review_schedule import (
    SkillReviewScheduleORM,
)
from stock_research_core.infrastructure.database.orm.tracked_security import TrackedSecurityORM
from stock_research_core.infrastructure.database.orm.user_progress import UserProgressORM
from stock_research_core.infrastructure.database.orm.virtual_portfolio import VirtualPortfolioORM

__all__ = [
    "AdaptiveDecisionORM",
    "AdaptiveDecisionReasonORM",
    "AdaptiveDecisionTargetSkillORM",
    "DiagnosticAssessmentItemORM",
    "DiagnosticAssessmentORM",
    "DiagnosticAssessmentSkillORM",
    "DiagnosticItemSkillORM",
    "ExerciseAdaptiveProfileORM",
    "ExerciseAnswerORM",
    "ExerciseAnswerOrderedOptionORM",
    "ExerciseAnswerSelectedOptionORM",
    "ExerciseAttemptORM",
    "ExerciseOptionORM",
    "ExerciseORM",
    "ExerciseSkillORM",
    "FinancialSkillORM",
    "HistoricalMarketScenarioORM",
    "HistoricalMarketScenarioPrimarySkillORM",
    "HistoricalMarketScenarioSecondarySkillORM",
    "LearnerProfileORM",
    "LearningModuleORM",
    "LearningPathORM",
    "LearningSessionActivityORM",
    "LearningSessionORM",
    "LessonORM",
    "LessonSecondarySkillORM",
    "MarketBarORM",
    "MarketDataIngestionRunORM",
    "MarketDataQualityIssueORM",
    "MisconceptionEvidenceAttemptORM",
    "MisconceptionORM",
    "PortfolioDecisionJournalEntryORM",
    "PortfolioHoldingORM",
    "PortfolioJournalAssumptionORM",
    "PortfolioJournalInformationItemORM",
    "PortfolioJournalRiskTagORM",
    "PortfolioPositionValuationORM",
    "PortfolioRiskAssessmentORM",
    "PortfolioRiskFeedbackCodeORM",
    "PortfolioRiskSkillORM",
    "PortfolioTransactionORM",
    "PortfolioValuationRunORM",
    "PortfolioValuationSnapshotORM",
    "ScenarioGenerationRunORM",
    "ScenarioOptionRubricFeedbackCodeORM",
    "ScenarioOptionRubricORM",
    "ScenarioOutcomeORM",
    "ScenarioSecurityORM",
    "ScenarioSubmissionFeedbackCodeORM",
    "ScenarioSubmissionORM",
    "SecurityORM",
    "SkillMasteryORM",
    "SkillPrerequisiteORM",
    "SkillReviewScheduleORM",
    "TrackedSecurityORM",
    "UserProgressORM",
    "VirtualPortfolioORM",
]
