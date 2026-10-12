"""Route-level tests using Flask's test client."""
import io

import app as app_module
import pytest


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    app_module._cache.clear()
    with app_module.app.test_client() as c:
        yield c
    app_module._cache.clear()


def test_health(client):
    assert client.get("/api/health").status_code == 200


def test_settings_reports_missing_key(client):
    body = client.get("/api/settings").get_json()

    assert body == {"has_api_key": False, "key_preview": ""}


def test_settings_masks_key(client, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "abcdefgh12345678")
    body = client.get("/api/settings").get_json()

    assert body["has_api_key"] is True
    assert body["key_preview"].endswith("5678")
    assert "abcdefgh" not in body["key_preview"]


def test_save_settings_requires_key(client):
    assert client.post("/api/settings", json={"api_key": "  "}).status_code == 400


def test_save_settings_sets_environment_for_session(client, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "")
    assert client.post("/api/settings", json={"api_key": "new-key"}).status_code == 200

    import os

    assert os.environ["YOUTUBE_API_KEY"] == "new-key"


def test_dashboard_and_analysis_routes_404_before_upload(client):
    for route in ("/api/dashboard", "/api/heatmap", "/api/keywords/weighted", "/api/duration", "/api/descriptions"):
        assert client.get(route).status_code == 404, route


def test_upload_requires_file(client):
    assert client.post("/api/dashboard/upload").status_code == 400


def test_upload_then_read_back_dashboard(client, studio_csv):
    with open(studio_csv, "rb") as fh:
        data = {"file": (io.BytesIO(fh.read()), "export.csv")}
    response = client.post("/api/dashboard/upload", data=data, content_type="multipart/form-data")

    assert response.status_code == 200
    body = response.get_json()
    assert len(body["rows"]) == 3
    assert "metadata" not in body  # raw metadata is not sent to the browser

    again = client.get("/api/dashboard").get_json()
    assert again["video_id_col"] == "Content"


def test_heatmap_and_duration_after_upload(client, studio_csv):
    with open(studio_csv, "rb") as fh:
        client.post(
            "/api/dashboard/upload",
            data={"file": (io.BytesIO(fh.read()), "export.csv")},
            content_type="multipart/form-data",
        )

    heatmap = client.get("/api/heatmap?metric=Views").get_json()
    assert sum(d["value"] for d in heatmap["calendar"]) == 600

    duration = client.get("/api/duration?metric=Views").get_json()
    assert {b["bucket"] for b in duration["buckets"]} == {"8-15s", "1-4m", "9-15m"}
