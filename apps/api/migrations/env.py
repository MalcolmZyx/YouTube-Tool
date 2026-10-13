"""Alembic environment: connects migrations to our models and our settings.

Run from apps/api:
    alembic upgrade head                          apply all migrations
    alembic revision --autogenerate -m "message"  draft a migration from model changes (then review it!)
    alembic check                                 fail if the models and the migrations disagree
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

import db.models  # noqa: F401  (importing registers every table on Base.metadata)
from config import settings
from db.base import Base

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False keeps the application's own loggers working when migrations
    # are run from inside the app or its tests.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    # Precedence: a URL passed from Python code (tests migrate a scratch database this way), then
    # `alembic -x url=...` on the command line, then the application's configured database.
    return (
        config.attributes.get("url")
        or context.get_x_argument(as_dictionary=True).get("url")
        or settings.database_url
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (`alembic upgrade head --sql`)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
