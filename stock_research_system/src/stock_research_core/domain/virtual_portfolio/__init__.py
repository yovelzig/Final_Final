"""FinQuest virtual-portfolio domain: enums and models with no
infrastructure dependencies. Kept independent from `domain.learning`,
`domain.adaptive_learning`, and `domain.market_scenarios` - other
entities (learners, securities, skills) are referenced as plain UUIDs,
not imported types, except the market-data domain's `Security` /
`MarketBar`, which this feature is built directly on top of.
"""
