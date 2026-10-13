"""Session handling and the maintenance CLI, against the scratch test database."""
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

import db.session as session_module
from db.__main__ import main
from db.models import Client, Metric


@pytest.fixture
def use_test_database(db_engine, monkeypatch):
    """Point get_session at the scratch database, and clean up the rows these tests really commit."""
    monkeypatch.setattr(session_module, "get_engine", lambda: db_engine)
    yield
    with Session(db_engine) as cleanup, cleanup.begin():
        cleanup.execute(delete(Client))
        cleanup.execute(delete(Metric))  # also removes the aliases (ON DELETE CASCADE)


def _names(db_engine):
    with Session(db_engine) as check:
        return set(check.scalars(select(Client.name)))


def test_get_session_commits_on_success(db_engine, use_test_database):
    dependency = session_module.get_session()
    session = next(dependency)
    session.add(Client(name="committed"))
    with pytest.raises(StopIteration):
        next(dependency)

    assert _names(db_engine) == {"committed"}


def test_get_session_rolls_back_on_error(db_engine, use_test_database):
    dependency = session_module.get_session()
    session = next(dependency)
    session.add(Client(name="discarded"))
    session.flush()
    with pytest.raises(RuntimeError):
        dependency.throw(RuntimeError("request failed"))

    assert _names(db_engine) == set()


def test_sync_catalog_command_loads_the_catalog(db_engine, use_test_database, capsys):
    assert main(["sync-catalog"], engine=db_engine) == 0

    with Session(db_engine) as check:
        assert check.scalar(select(func.count()).select_from(Metric)) > 50
    assert "Metric catalog synced" in capsys.readouterr().out
