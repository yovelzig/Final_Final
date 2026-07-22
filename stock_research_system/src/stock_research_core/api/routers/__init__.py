"""FastAPI routers: one module per FinQuest bounded context. Every route
here is a thin translation layer - it validates ownership, calls an
existing Phase 1-8 application service, and maps the result onto a
response DTO. No business logic (grading, mastery, adaptive, scenario,
portfolio, retrieval, guardrail) is ever reimplemented here.
"""
