"""Historical market scenario engine: learner-safe result models,
repository/calculator/grading Protocols, and the orchestrating
`HistoricalMarketScenarioService`.

`HistoricalMarketScenarioService` and `MarketScenarioLearningOrchestrator`
are intentionally not re-exported here (same reasoning as
`application.learning`'s `__init__.py`): import them directly from
`service.py` / `orchestrator.py` to avoid a circular import through
`application.persistence.ports`.
"""
