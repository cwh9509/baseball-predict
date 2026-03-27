"""
Alembic environment configuration
Integrates with SQLAlchemy async engine using asyncpg driver
"""
import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.core.database import Base
import app.models  # noqa: F401

target_metadata = Base.metadata


DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://baseball:baseball@localhost:5432/baseball")


def run_migrations_offline() -> None:
    """Offline mode (generate SQL script only)"""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Online mode (apply migrations to real DB)"""
    engine = create_async_engine(DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
