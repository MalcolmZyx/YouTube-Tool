"""Shared test setup.

Tests must never reach the real YouTube API or use a developer's real key, so the key is
blanked before the app is imported (python-dotenv will not override an existing variable)
and any outbound HTTP call fails loudly.
"""
import os

os.environ["YOUTUBE_API_KEY"] = ""

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
