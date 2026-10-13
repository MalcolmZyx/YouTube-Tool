"""Tests for the request-level protections and the hardening fixes."""
import io
import logging

import pytest
import requests
from fastapi.testclient import TestClient

import deps
from app import app
from config import settings
from security import RedactingFormatter


@pytest.fixture
def client():
    deps.dataset_cache.clear()
    with TestClient(app) as c:
        yield c
    deps.dataset_cache.clear()


# ── cross-site requests ─────────────────────────────────────────────────────


def test_state_changing_request_from_a_foreign_origin_is_rejected(client):
    response = client.post(
        "/api/dashboard/upload",
        files={"file": ("x.csv", b"Content,Views\nAAAAAAAAAAA,1\n")},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert response.json() == {"error": "Origin not allowed"}
    assert "dataset" not in deps.dataset_cache  # nothing was processed


def test_foreign_origin_cannot_change_the_api_key(client, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "original")
    response = client.post(
        "/api/settings", json={"api_key": "attacker"}, headers={"Origin": "https://evil.example"}
    )

    assert response.status_code == 403


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173"])
def test_our_own_origins_are_allowed(client, monkeypatch, origin):
    monkeypatch.setenv("YOUTUBE_API_KEY", "")
    response = client.post("/api/settings", json={"api_key": "mine"}, headers={"Origin": origin})

    assert response.status_code == 200


def test_requests_without_an_origin_header_are_allowed(client):
    """curl, scripts and tests do not send Origin; only browsers do."""
    assert client.post("/api/settings", json={"api_key": " "}).status_code == 400  # reached the handler


def test_reads_are_not_blocked_by_the_origin_guard(client):
    """Reading from another origin is stopped by CORS in the browser, not by this guard."""
    assert client.get("/api/health", headers={"Origin": "https://evil.example"}).status_code == 200


# ── DNS rebinding ───────────────────────────────────────────────────────────


def test_unknown_host_header_is_rejected(client):
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400


# ── upload limits ───────────────────────────────────────────────────────────


def test_declared_oversized_body_is_refused_early(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    big = b"Content,Views\n" + b"AAAAAAAAAAA,1\n" * 20_000  # ~280 KB, well past 64 KB overhead allowance

    response = client.post("/api/dashboard/upload", files={"file": ("x.csv", big)})

    assert response.status_code == 413
    assert "too large" in response.json()["error"].lower()


def test_oversized_file_is_refused_while_copying(client, monkeypatch):
    """Content-Length can be missing or wrong, so the route enforces the limit as well."""
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    small = b"Content,Views\nAAAAAAAAAAA,1\n"  # under the early-refusal allowance, over a 0 MB limit

    response = client.post("/api/dashboard/upload", files={"file": ("x.csv", small)})

    assert response.status_code == 413


def test_too_many_rows_is_refused_with_a_clear_message(client, monkeypatch, studio_csv):
    monkeypatch.setattr(settings, "max_rows", 2)
    with open(studio_csv, "rb") as fh:
        response = client.post("/api/dashboard/upload", files={"file": ("export.csv", fh.read())})

    assert response.status_code == 413
    assert "limit is 2" in response.json()["error"]


def test_row_limit_field_lets_a_large_export_be_processed_partially(client, monkeypatch, studio_csv):
    monkeypatch.setattr(settings, "max_rows", 2)
    with open(studio_csv, "rb") as fh:
        response = client.post(
            "/api/dashboard/upload", files={"file": ("export.csv", fh.read())}, data={"num_rows": "2"}
        )

    assert response.status_code == 200
    assert len(response.json()["rows"]) == 2


def test_no_temp_files_are_left_behind_after_a_refused_upload(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))

    client.post("/api/dashboard/upload", files={"file": ("x.csv", b"Content,Views\nAAAAAAAAAAA,1\n")})

    assert list(tmp_path.iterdir()) == []


# ── input handling ──────────────────────────────────────────────────────────


def test_autocomplete_topic_is_url_encoded_not_spliced_into_the_url(monkeypatch):
    seen = {}

    class _Response:
        text = ""

        def raise_for_status(self):
            pass

    def fake_get(url, **kwargs):
        seen["url"] = url
        seen["params"] = kwargs.get("params")
        return _Response()

    monkeypatch.setattr(requests, "get", fake_get)
    deps.researcher_svc.get_ideas("cats&client=firefox&hl=xx")

    assert "cats" not in seen["url"]  # nothing user-supplied in the URL string
    assert seen["params"] == {"client": "youtube", "q": "cats&client=firefox&hl=xx"}


def test_openpyxl_is_protected_by_defusedxml():
    from openpyxl.xml import DEFUSEDXML

    assert DEFUSEDXML is True


# ── logging ─────────────────────────────────────────────────────────────────


def test_log_formatter_redacts_api_keys():
    record = logging.LogRecord(
        "x", logging.ERROR, __file__, 1,
        "GET https://www.googleapis.com/youtube/v3/videos?id=abc&key=AIzaSECRET123&part=snippet", None, None,
    )

    output = RedactingFormatter("%(message)s").format(record)

    assert "AIzaSECRET123" not in output
    assert "key=<redacted>" in output
    assert "part=snippet" in output  # the rest of the URL is preserved


def test_log_formatter_redacts_keys_inside_tracebacks():
    try:
        raise RuntimeError("failed: https://example.test/?key=TOPSECRET&x=1")
    except RuntimeError:
        import sys

        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "boom", None, sys.exc_info())

    assert "TOPSECRET" not in RedactingFormatter("%(message)s").format(record)


# ── docs switch ─────────────────────────────────────────────────────────────


def test_docs_are_served_when_enabled(client):
    assert client.get("/docs").status_code == 200


def test_upload_returns_json_even_for_empty_file_body(client):
    response = client.post("/api/dashboard/upload", files={"file": ("x.csv", io.BytesIO(b""))})

    assert response.status_code == 422
