"""Concrete, replaceable infrastructure adapters for the grounded AI tutor:
embedding providers (a local sentence-transformer adapter and a
test-only deterministic fake), tutor-model providers (the deterministic
extractive tutor and an OpenAI-compatible HTTP adapter), and local
document parsers. None of these modules is imported at package level -
importing `stock_research_core.infrastructure.ai_tutor` never loads a
model, opens a database connection, or makes a network request; import
the concrete module you need directly.
"""
