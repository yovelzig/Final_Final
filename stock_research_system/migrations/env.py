"""Alembic environment configured for the async SQLAlchemy engine.

Alembic migrations are the source of truth for the schema; application
startup never calls `Base.metadata.create_all()`.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import stock_research_core.infrastructure.database.orm  # noqa: F401 - registers all ORM models
from stock_research_core.infrastructure.database.base import Base
from stock_research_core.infrastructure.database.config import DatabaseSettings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

settings = DatabaseSettings()
# ALEMBIC_DATABASE_URL lets the integration test suite point migrations at
# the test database without touching the development database URL.
database_url = os.environ.get("ALEMBIC_DATABASE_URL") or settings.database_url
config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
