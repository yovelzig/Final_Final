"""PostgreSQL/TimescaleDB persistence infrastructure.

Importing this package never opens a database connection: engines and
sessions are only created when a caller explicitly asks for one.
"""

from stock_research_core.infrastructure.database.config import DatabaseSettings, mask_database_url
from stock_research_core.infrastructure.database.engine import (
    check_database_connection,
    create_database_engine,
    create_session_factory,
)
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

__all__ = [
    "DatabaseSettings",
    "SqlAlchemyUnitOfWork",
    "check_database_connection",
    "create_database_engine",
    "create_session_factory",
    "mask_database_url",
]
