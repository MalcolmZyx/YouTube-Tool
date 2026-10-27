"""Shared test setup.

Tests must never reach the real YouTube API or use a developer's real key, so the key is
blanked before the app is imported (python-dotenv will not override an existing variable)
and any outbound HTTP call fails loudly.
"""
import os
from pathlib import Path

# Pin every setting the tests depend on, so a developer's local .env cannot change test results.
# Variables that are already set win over the .env file (see config.py).
os.environ["YOUTUBE_API_KEY"] = ""
os.environ["CORS_ORIGINS"] = "http://localhost:5173,http://127.0.0.1:5173"
os.environ["ALLOWED_HOSTS"] = "localhost,127.0.0.1,testserver"  # "testserver" is TestClient's host name
os.environ["DOCS_ENABLED"] = "true"
os.environ["MAX_UPLOAD_MB"] = "5"
os.environ["MAX_ROWS"] = "5000"

import pytest  # noqa: E402
import requests  # noqa: E402


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("Test attempted a real HTTP request; monkeypatch requests.get instead.")

    monkeypatch.setattr(requests, "get", _blocked)
    monkeypatch.setattr(requests, "post", _blocked)
    monkeypatch.setenv("YOUTUBE_API_KEY", "")


# ── MongoDB fixture ─────────────────────────────────────────────────────────
#
# Public YouTube data lives in MongoDB. Tests that need it use a throw-away database ("ytstudio_test"), dropped before
# and after. Without a reachable MongoDB they are skipped, unless REQUIRE_MONGO=1 (set in CI).


@pytest.fixture
def mongo(monkeypatch):
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError

    from config import settings
    from youtube import comment_store, store

    url = os.environ.get("TEST_MONGO_URL", "mongodb://ytstudio:ytstudio_dev@127.0.0.1:27017/?authSource=admin")
    client = MongoClient(url, serverSelectionTimeoutMS=2000, tz_aware=True)
    try:
        client.admin.command("ping")
    except PyMongoError:
        if os.environ.get("REQUIRE_MONGO") == "1":
            raise
        pytest.skip("MongoDB is not reachable; run `docker compose up -d`")
    monkeypatch.setattr(settings, "mongo_url", url)
    monkeypatch.setattr(settings, "mongo_db", "ytstudio_test")
    client.drop_database("ytstudio_test")
    store._prepare.cache_clear()  # so the indexes are created in the fresh database
    comment_store._prepare.cache_clear()
    yield client["ytstudio_test"][store.COLLECTION]
    client.drop_database("ytstudio_test")
    store._prepare.cache_clear()
    comment_store._prepare.cache_clear()
    client.close()


# ── database fixtures ───────────────────────────────────────────────────────
#
# Database tests run against a throw-away database ("ytstudio_test") on the same Postgres server
# the app uses, built by running the real Alembic migrations. They never touch the development
# database. Without a reachable Postgres they are skipped, unless REQUIRE_DB=1 (set in CI), where a
# missing database must fail the build rather than silently skip the tests.

API_DIR = Path(__file__).resolve().parents[1]
TEST_DB_NAME = "ytstudio_test"


@pytest.fixture(scope="session")
def db_engine():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import OperationalError

    from config import settings

    base_url = make_url(os.environ.get("TEST_DATABASE_URL", settings.database_url))
    assert base_url.database != TEST_DB_NAME or "TEST_DATABASE_URL" in os.environ
    admin = create_engine(base_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
            conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    except OperationalError as exc:
        if os.environ.get("REQUIRE_DB"):
            raise
        pytest.skip(f"Postgres is not reachable ({exc.orig.__class__.__name__}); run `docker compose up -d`")

    test_url = base_url.set(database=TEST_DB_NAME)
    config = Config(str(API_DIR / "alembic.ini"))
    config.attributes["url"] = test_url.render_as_string(hide_password=False)
    command.upgrade(config, "head")

    engine = create_engine(test_url)
    yield engine
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
    admin.dispose()


@pytest.fixture
def db_session(db_engine):
    """A session whose work is rolled back after the test, so tests cannot affect each other."""
    from sqlalchemy.orm import Session

    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def catalog_session(db_session):
    """A session with the metric catalog seeded."""
    from db.catalog import sync_metric_catalog

    sync_metric_catalog(db_session)
    return db_session


@pytest.fixture
def studio_csv(tmp_path):
    """A small Studio-style export: a Total row first, then three videos."""
    path = tmp_path / "export.csv"
    path.write_text(
        "Content,Video title,Video publish time,Duration,Views,Impressions click-through rate (%),Dislikes\n"
        "Total,,,,600,4.5,0\n"
        "AAAAAAAAAAA,First,2024-01-01,10,100,5.0,0\n"
        "BBBBBBBBBBB,Second,2024-01-01,120,200,4.0,0\n"
        "CCCCCCCCCCC,Third,2024-01-03,600,300,4.5,0\n",
        encoding="utf-8",
    )
    return str(path)
