"""Application layer: orchestrates domain models and port contracts.

This layer may depend on `stock_research_core.domain` and
`stock_research_core.contracts`, but must never import a concrete
infrastructure library (yfinance, pandas, a database driver, etc.).
"""
