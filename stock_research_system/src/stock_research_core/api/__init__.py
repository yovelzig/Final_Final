"""FinQuest product API: FastAPI transport layer over the existing
Phase 1-8 application services.

Nothing in this package (or any subpackage) may be imported by
`domain.*` or `application.*` - FastAPI belongs only here. Importing
this package never connects to a database, opens an HTTP client, or
loads a model: `api.main.app` is built by `api.app_factory.create_app()`,
which defers all of that to its `lifespan` (startup/shutdown), not to
module import.
"""
