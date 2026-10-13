"""The database-backed dashboard and analyses for a client."""
import uuid

import pytest
from fastapi.testclient import TestClient
from studio_fixtures import SIMPLE_HEADERS, simple_rows, write_xlsx

from app import app
from db.session import get_session
from synthetic.generator import PROFILES, write_export


@pytest.fixture
def api(catalog_session):
    app.dependency_overrides[get_session] = lambda: catalog_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_client(api, path, name="Acme", **form):
    client = api.post("/api/clients", json={"name": name}).json()
    with open(path, "rb") as fh:
        response = api.post(f"/api/clients/{client['id']}/uploads", files={"file": (path.name, fh.read())}, data=form)
    assert response.status_code == 201, response.text
    return client["id"], response.json()["upload_id"]


@pytest.fixture
def simple(api, tmp_path):
    path = write_xlsx(tmp_path / "Table data.xlsx", SIMPLE_HEADERS, simple_rows())
    return make_client(api, path)


def test_dashboard_matches_the_export(api, simple):
    client_id, _ = simple

    body = api.get(f"/api/clients/{client_id}/dashboard").json()

    assert body["video_id_col"] == "Content"
    assert [r["Views"] for r in body["rows"]] == [300, 200, 100]  # most viewed first
    assert body["total_row"]["Views"] == 600  # the Total row, not a sum over the videos
    assert "Views" in body["numeric_columns"]
    assert {r["Video title"] for r in body["rows"]} == {"First", "Second", "Third"}
    # Known limitation: the display pipeline (shared with the old upload flow) turns a blank into 0. The database
    # keeps the difference; the audit engine will read it from there instead of from this table.
    assert body["rows"][0]["Likes"] == 0


def test_analyses_read_from_the_database(api, simple):
    client_id, _ = simple

    heat = api.get(f"/api/clients/{client_id}/heatmap?metric=Views").json()
    duration = api.get(f"/api/clients/{client_id}/duration?metric=Views").json()

    assert sum(p["value"] for p in heat["calendar"]) == 600
    assert "Views" in heat["available_metrics"]
    assert sum(b["count"] for b in duration["buckets"]) == 3
    # tags and descriptions need YouTube API data, which is not stored yet
    assert api.get(f"/api/clients/{client_id}/keywords/weighted").json() == {"tags": []}
    assert api.get(f"/api/clients/{client_id}/descriptions").json() == {"videos": [], "total": 0}


def test_unknown_client_and_empty_client_are_404(api):
    assert api.get(f"/api/clients/{uuid.uuid4()}/dashboard").status_code == 404
    empty = api.post("/api/clients", json={"name": "Empty"}).json()

    response = api.get(f"/api/clients/{empty['id']}/dashboard")

    assert response.status_code == 404 and "No data" in response.json()["error"]


def test_clients_never_see_each_others_data(api, tmp_path):
    first = make_client(api, write_export(PROFILES[1], tmp_path), "One")
    second = make_client(api, write_xlsx(tmp_path / "t.xlsx", SIMPLE_HEADERS, simple_rows()), "Two")

    assert len(api.get(f"/api/clients/{first[0]}/dashboard").json()["rows"]) == PROFILES[1].videos
    assert len(api.get(f"/api/clients/{second[0]}/dashboard").json()["rows"]) == 3
    # asking for another client's upload is a 404, not their data
    assert api.get(f"/api/clients/{second[0]}/dashboard?upload_id={first[1]}").status_code == 404


def test_the_latest_upload_is_the_default_and_an_older_one_can_be_chosen(api, tmp_path):
    client_id, first_upload = make_client(
        api, write_xlsx(tmp_path / "a.xlsx", SIMPLE_HEADERS, simple_rows()), period_lifetime="true"
    )
    newer_rows = simple_rows()
    newer_rows[1][4] = 999
    with open(write_xlsx(tmp_path / "b.xlsx", SIMPLE_HEADERS, newer_rows), "rb") as fh:
        second = api.post(f"/api/clients/{client_id}/uploads", files={"file": ("b.xlsx", fh.read())}).json()

    latest = api.get(f"/api/clients/{client_id}/dashboard").json()
    older = api.get(f"/api/clients/{client_id}/dashboard?upload_id={first_upload}").json()

    assert second["upload_id"] != first_upload
    assert latest["rows"][0]["Views"] == 999 and older["rows"][0]["Views"] == 300


def test_synthetic_channel_flows_through_every_analysis(api, tmp_path):
    client_id, _ = make_client(api, write_export(PROFILES[0], tmp_path), "Synthetic")

    body = api.get(f"/api/clients/{client_id}/dashboard").json()
    heat = api.get(f"/api/clients/{client_id}/heatmap?metric=Views").json()

    assert len(body["rows"]) == PROFILES[0].videos
    assert sum(p["value"] for p in heat["calendar"]) == pytest.approx(sum(r["Views"] for r in body["rows"]))
