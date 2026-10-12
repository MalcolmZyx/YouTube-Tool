"""Route-level tests using FastAPI's TestClient."""
import io
import os

import pytest
from fastapi.testclient import TestClient
from googleapiclient.errors import HttpError
from httplib2 import Response
from openpyxl import Workbook

import deps
from app import app


@pytest.fixture
def client():
    deps.dataset_cache.clear()
    with TestClient(app) as c:
        yield c
    deps.dataset_cache.clear()


@pytest.fixture
def uploaded(client, studio_csv):
    """A client with the sample export already uploaded."""
    with open(studio_csv, "rb") as fh:
        response = client.post("/api/dashboard/upload", files={"file": ("export.csv", fh.read())})
    assert response.status_code == 200
    return client


def _xlsx_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["Content", "Views"])
    ws.append(["AAAAAAAAAAA", 10])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── system ──────────────────────────────────────────────────────────────────


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok", "cache_loaded": False}


def test_settings_reports_missing_key(client):
    assert client.get("/api/settings").json() == {"has_api_key": False, "key_preview": ""}


def test_settings_masks_key(client, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "abcdefgh12345678")
    body = client.get("/api/settings").json()

    assert body["has_api_key"] is True
    assert body["key_preview"].endswith("5678")
    assert "abcdefgh" not in body["key_preview"]


def test_save_settings_rejects_blank_key(client):
    response = client.post("/api/settings", json={"api_key": "  "})

    assert response.status_code == 400
    assert response.json() == {"error": "api_key is required"}


def test_save_settings_requires_the_field(client):
    response = client.post("/api/settings", json={})

    assert response.status_code == 422
    assert "api_key" in response.json()["error"]


def test_save_settings_sets_environment_for_session(client, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "")

    assert client.post("/api/settings", json={"api_key": "new-key"}).status_code == 200
    assert os.environ["YOUTUBE_API_KEY"] == "new-key"


# ── error shape ─────────────────────────────────────────────────────────────


def test_errors_use_the_error_key_the_frontend_reads(client):
    response = client.get("/api/dashboard")

    assert response.status_code == 404
    assert response.json() == {"error": "No data loaded. Please upload a file."}


def test_unknown_route_uses_the_same_shape(client):
    response = client.get("/api/nope")

    assert response.status_code == 404
    assert "error" in response.json()


def test_unexpected_errors_are_generic(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("secret internals")

    monkeypatch.setattr(deps.heatmap_svc, "compute", boom)
    deps.dataset_cache["dataset"] = {"rows": [], "numeric_columns": [], "percent_columns": []}
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get("/api/heatmap")
    finally:
        deps.dataset_cache.clear()

    assert response.status_code == 500
    assert response.json() == {"error": "Internal server error"}


# ── analysis routes need a dataset ──────────────────────────────────────────


@pytest.mark.parametrize(
    "route",
    ["/api/dashboard", "/api/heatmap", "/api/keywords/weighted", "/api/keywords/top-vs-bottom",
     "/api/duration", "/api/descriptions"],
)
def test_routes_404_before_upload(client, route):
    assert client.get(route).status_code == 404


# ── upload ──────────────────────────────────────────────────────────────────


def test_upload_requires_a_file(client):
    assert client.post("/api/dashboard/upload").status_code == 422


def test_upload_rejects_unsupported_extension(client):
    response = client.post("/api/dashboard/upload", files={"file": ("notes.txt", b"hello")})

    assert response.status_code == 400
    assert "Unsupported" in response.json()["error"]


def test_upload_extension_check_is_case_insensitive(client):
    response = client.post("/api/dashboard/upload", files={"file": ("EXPORT.XLSX", _xlsx_bytes())})

    assert response.status_code == 200
    assert [r["Content"] for r in response.json()["rows"]] == ["AAAAAAAAAAA"]


def test_upload_unreadable_excel_is_a_422_not_a_crash(client):
    response = client.post("/api/dashboard/upload", files={"file": ("broken.xlsx", b"not a real workbook")})

    assert response.status_code == 422
    assert "Could not read" in response.json()["error"]


def test_upload_then_read_back_dashboard(uploaded):
    body = uploaded.get("/api/dashboard").json()

    assert len(body["rows"]) == 3
    assert body["video_id_col"] == "Content"
    assert "metadata" not in body  # raw API metadata is never sent to the browser


def test_upload_num_rows_limits_videos(client, studio_csv):
    with open(studio_csv, "rb") as fh:
        response = client.post(
            "/api/dashboard/upload", files={"file": ("export.csv", fh.read())}, data={"num_rows": "2"}
        )

    assert len(response.json()["rows"]) == 2


# ── analysis ────────────────────────────────────────────────────────────────


def test_heatmap_after_upload(uploaded):
    body = uploaded.get("/api/heatmap?metric=Views").json()

    assert sum(d["value"] for d in body["calendar"]) == 600
    assert "Views" in body["available_metrics"]


def test_duration_after_upload(uploaded):
    body = uploaded.get("/api/duration?metric=Views").json()

    assert {b["bucket"] for b in body["buckets"]} == {"8-15s", "1-4m", "9-15m"}


def test_descriptions_after_upload_with_no_api_key_is_empty(uploaded):
    assert uploaded.get("/api/descriptions").json() == {"videos": [], "total": 0}


@pytest.mark.parametrize("value", ["abc", "0", "-3", "1000"])
def test_top_n_is_validated(uploaded, value):
    response = uploaded.get(f"/api/keywords/weighted?top_n={value}")

    assert response.status_code == 422
    assert "top_n" in response.json()["error"]


def test_keywords_without_api_metadata_are_empty(uploaded):
    assert uploaded.get("/api/keywords/weighted").json() == {"tags": []}


# ── researcher ──────────────────────────────────────────────────────────────


def test_search_requires_api_key(client):
    response = client.post("/api/researcher/search", json={"query": "x"})

    assert response.status_code == 400
    assert "API key" in response.json()["error"]


def test_search_rejects_blank_query(client, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")

    assert client.post("/api/researcher/search", json={"query": "  "}).status_code == 400


@pytest.mark.parametrize("payload", [{"query": "x", "order": "bogus"}, {"query": "x", "max_results": 500}])
def test_search_validates_options(client, monkeypatch, payload):
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")

    assert client.post("/api/researcher/search", json=payload).status_code == 422


def test_search_returns_videos_and_tag_scores(client, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    video = {
        "video_id": "AAAAAAAAAAA", "title": "T", "url": "u", "channel": "c", "published_at": "2024-01-01",
        "views": 99, "likes": 1, "comment_count": 0, "tags": ["Alpha"], "thumbnail": "", "description": "",
    }
    monkeypatch.setattr(deps.researcher_svc, "search", lambda **kwargs: [video])

    body = client.post("/api/researcher/search", json={"query": "x"}).json()

    assert body["total"] == 1
    assert body["tags"] == [{"tag": "alpha", "score": 2.0}]


def test_search_quota_error_is_429_and_never_leaks_the_key(client, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "SECRET-KEY-123")
    uri = "https://www.googleapis.com/youtube/v3/search?key=SECRET-KEY-123"
    error = HttpError(
        Response({"status": 403}),
        b'{"error": {"message": "The request cannot be completed because you have exceeded your quota."}}',
        uri=uri,
    )

    def fail(**kwargs):
        raise error

    monkeypatch.setattr(deps.researcher_svc, "search", fail)
    response = client.post("/api/researcher/search", json={"query": "x"})

    assert response.status_code == 429
    assert "SECRET-KEY-123" not in response.text


def test_ideas_requires_topic(client):
    assert client.get("/api/researcher/ideas").status_code == 400


def test_ideas_returns_suggestions(client, monkeypatch):
    monkeypatch.setattr(deps.researcher_svc, "get_ideas", lambda topic: [f"{topic} one", f"{topic} two"])

    assert client.get("/api/researcher/ideas?topic=cats").json() == {
        "ideas": ["cats one", "cats two"],
        "topic": "cats",
    }


# ── CORS and docs ───────────────────────────────────────────────────────────


def _preflight(client, origin):
    return client.options(
        "/api/health", headers={"Origin": origin, "Access-Control-Request-Method": "GET"}
    )


def test_cors_allows_only_configured_origins(client):
    allowed = _preflight(client, "http://localhost:5173")
    blocked = _preflight(client, "https://evil.example")

    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in blocked.headers


def test_openapi_schema_is_published(client):
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/dashboard/upload" in paths
    assert "/api/researcher/search" in paths
