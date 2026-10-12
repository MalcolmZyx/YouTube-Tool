"""Shared test setup.

Tests must never reach the real YouTube API or use a developer's real key, so the key is
blanked before the app is imported (python-dotenv will not override an existing variable)
and any outbound HTTP call fails loudly.
"""
import os

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
