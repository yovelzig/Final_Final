"""Infrastructure adapters for Phase 11 background jobs, distributed
locking, metrics, tracing, and structured logging.

Importing this package must never create a Redis connection, a Celery
app connection, or any other network resource - all such resources are
created lazily, inside explicit constructors/factory functions called
from a composition root (`api.app_factory`, `cli.*`, or a Celery worker
entry point), never at module import time.
"""
