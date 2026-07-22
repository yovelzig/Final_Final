"""FinQuest historical market scenario domain: enums and models with no
infrastructure dependencies.

References the market-data domain (`stock_research_core.domain.models`)
and the learning domain (`stock_research_core.domain.learning`) only by
UUID (`focal_security_id`, `exercise_id`, `primary_skill_ids`, ...) or by
reusing the small, stable `ConfidenceLevel` enum - never by importing
`Security`, `MarketBar`, `Exercise`, or any other learning/market-data
model here. Cross-domain composition (e.g. a learner-safe view that
embeds a `Security` and `ExerciseOption`) happens one layer up, in
`stock_research_core.application.market_scenarios`.
"""
