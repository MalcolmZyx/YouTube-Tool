"""Engine and session handling.

The engine is created on first use, not at import, so the API (and its tests) can start
without a database until a route actually needs one.
"""
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import settings


@lru_cache
def get_engine() -> Engine:
    # pool_pre_ping discards connections the server has closed, instead of failing a request.
    return create_engine(settings.database_url, pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, committed on success, rolled back on error."""
    with sessionmaker(bind=get_engine(), expire_on_commit=False)() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
