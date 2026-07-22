"""ORM-to-domain mapper functions. Never return ORM instances as domain results."""

from stock_research_core.infrastructure.database.mappers.adaptive_learning_mappers import (
    adaptive_decision_orm_to_domain,
    diagnostic_assessment_item_orm_to_domain,
    diagnostic_assessment_orm_to_domain,
    exercise_adaptive_profile_orm_to_domain,
    learning_session_activity_orm_to_domain,
    learning_session_orm_to_domain,
    skill_review_schedule_orm_to_domain,
)
from stock_research_core.infrastructure.database.mappers.learning_mappers import (
    exercise_answer_orm_to_domain,
    exercise_attempt_orm_to_domain,
    exercise_option_orm_to_domain,
    exercise_orm_to_domain,
    learner_profile_orm_to_domain,
    learning_module_orm_to_domain,
    learning_path_orm_to_domain,
    lesson_orm_to_domain,
    misconception_orm_to_domain,
    skill_mastery_orm_to_domain,
    skill_orm_to_domain,
    user_progress_orm_to_domain,
)
from stock_research_core.infrastructure.database.mappers.market_bar_mapper import (
    market_bar_orm_to_domain,
)
from stock_research_core.infrastructure.database.mappers.security_mapper import (
    security_orm_to_domain,
)
from stock_research_core.infrastructure.database.mappers.tracked_security_mapper import (
    tracked_security_orm_to_domain,
)
from stock_research_core.infrastructure.database.mappers.virtual_portfolio_mappers import (
    portfolio_decision_journal_entry_orm_to_domain,
    portfolio_holding_orm_to_domain,
    portfolio_position_valuation_orm_to_domain,
    portfolio_risk_assessment_orm_to_domain,
    portfolio_transaction_orm_to_domain,
    portfolio_valuation_run_orm_to_domain,
    portfolio_valuation_snapshot_orm_to_domain,
    virtual_portfolio_orm_to_domain,
)

__all__ = [
    "adaptive_decision_orm_to_domain",
    "diagnostic_assessment_item_orm_to_domain",
    "diagnostic_assessment_orm_to_domain",
    "exercise_adaptive_profile_orm_to_domain",
    "exercise_answer_orm_to_domain",
    "exercise_attempt_orm_to_domain",
    "exercise_option_orm_to_domain",
    "exercise_orm_to_domain",
    "learner_profile_orm_to_domain",
    "learning_module_orm_to_domain",
    "learning_path_orm_to_domain",
    "learning_session_activity_orm_to_domain",
    "learning_session_orm_to_domain",
    "lesson_orm_to_domain",
    "market_bar_orm_to_domain",
    "misconception_orm_to_domain",
    "portfolio_decision_journal_entry_orm_to_domain",
    "portfolio_holding_orm_to_domain",
    "portfolio_position_valuation_orm_to_domain",
    "portfolio_risk_assessment_orm_to_domain",
    "portfolio_transaction_orm_to_domain",
    "portfolio_valuation_run_orm_to_domain",
    "portfolio_valuation_snapshot_orm_to_domain",
    "security_orm_to_domain",
    "skill_mastery_orm_to_domain",
    "skill_orm_to_domain",
    "skill_review_schedule_orm_to_domain",
    "tracked_security_orm_to_domain",
    "user_progress_orm_to_domain",
    "virtual_portfolio_orm_to_domain",
]
