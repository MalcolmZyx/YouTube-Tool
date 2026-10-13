"""Publishing to the portal: what is sent, what is left out, and that the service key never leaks."""
import json
import math
import uuid

import pytest
import requests
from fastapi.testclient import TestClient
from studio_fixtures import SIMPLE_HEADERS, simple_rows, write_xlsx

from app import app
from config import settings
from db.models import Client
from db.session import get_session
from portal import client as portal
from synthetic.generator import PROFILES, write_export

KEY = "service-key-SECRET-123"
SNAPSHOT_PARAMS = {"on_conflict": "client_id,kind"}


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body if body is not None else []

    def json(self):
        return self._body


class FakePortal:
    """Stands in for the portal's REST API and records every call."""

    def __init__(self):
        self.calls, self.fail_with, self.snapshots = [], None, {}

    def __call__(self, method, url, params=None, headers=None, data=None, timeout=None):
        if self.fail_with:
            raise self.fail_with
        body = json.loads(data) if data else None
        self.calls.append({"method": method, "path": url.split("/rest/v1/")[1], "params": params,
                           "headers": headers, "body": body})
        if method == "POST" and url.endswith("published_snapshot"):
            self.snapshots = {row["kind"]: row for row in body}
        if method == "GET":
            return FakeResponse(body=[{"kind": k, "published_at": r["published_at"], "as_of": r["as_of"]}
                                      for k, r in self.snapshots.items()])
        return FakeResponse(201 if method == "POST" else 204)


@pytest.fixture
def api(catalog_session):
    app.dependency_overrides[get_session] = lambda: catalog_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def fake(monkeypatch):
    fake_portal = FakePortal()
    monkeypatch.setattr(settings, "portal_url", "http://portal.test")
    monkeypatch.setenv("PORTAL_SERVICE_KEY", KEY)
    monkeypatch.setattr(requests, "request", fake_portal)
    return fake_portal


def upload(api, client_id, path):
    with open(path, "rb") as fh:
        response = api.post(f"/api/clients/{client_id}/uploads", files={"file": (path.name, fh.read())})
    assert response.status_code == 201
    return response


@pytest.fixture
def client_id(api, tmp_path):
    created = api.post("/api/clients", json={"name": "Acme"}).json()
    upload(api, created["id"], write_export(PROFILES[0], tmp_path))
    return created["id"]


def test_without_configuration_nothing_is_sent_and_the_status_says_so(api, client_id, monkeypatch):
    monkeypatch.setattr(requests, "request", lambda *a, **k: pytest.fail("called the portal while unconfigured"))

    assert api.get(f"/api/clients/{client_id}/portal").json() == {"configured": False, "published": {}}
    assert api.post(f"/api/clients/{client_id}/portal/publish").status_code == 503
    assert api.delete(f"/api/clients/{client_id}").status_code == 200  # a local delete needs no portal


def test_publishing_sends_the_client_then_both_snapshots_with_the_service_key(api, client_id, fake):
    response = api.post(f"/api/clients/{client_id}/portal/publish")

    assert response.status_code == 200
    assert set(response.json()["published"]) == {"audit", "dashboard"}
    client_call, snapshot_call = fake.calls[0], fake.calls[1]
    assert client_call["path"] == "portal_client" and client_call["body"] == {"id": client_id, "display_name": "Acme"}
    assert snapshot_call["path"] == "published_snapshot" and snapshot_call["params"] == SNAPSHOT_PARAMS
    assert {row["kind"] for row in snapshot_call["body"]} == {"audit", "dashboard"}
    assert all(row["client_id"] == client_id for row in snapshot_call["body"])
    assert snapshot_call["headers"]["apikey"] == KEY and snapshot_call["headers"]["Authorization"] == f"Bearer {KEY}"


def test_the_snapshots_hold_only_export_data(api, client_id, fake):
    api.post(f"/api/clients/{client_id}/portal/publish")
    published = {row["kind"]: row["payload"] for row in fake.calls[1]["body"]}
    dashboard, audit = published["dashboard"], published["audit"]

    assert len(dashboard["rows"]) == PROFILES[0].videos
    assert dashboard["total_row"]["Views"] > 0
    text = json.dumps(published)
    for api_only in ("thumbnail_url", "video_description", "video_title", "category_id", '"tags"'):
        assert api_only not in text, api_only
    assert "filename" not in audit and "upload_id" not in audit
    assert {f["key"] for f in audit["findings"]} >= {"overview", "formats"}


def test_nan_and_dates_become_valid_json(api, client_id, fake):
    api.post(f"/api/clients/{client_id}/portal/publish")

    json.dumps(fake.calls[1]["body"], allow_nan=False)  # would raise on NaN or Infinity
    assert portal._clean({"a": math.nan, "b": [math.inf, 1.5]}) == {"a": None, "b": [None, 1.5]}


def test_publishing_again_replaces_and_unpublishing_removes(api, client_id, fake):
    api.post(f"/api/clients/{client_id}/portal/publish")
    api.post(f"/api/clients/{client_id}/portal/publish")
    posts = [c for c in fake.calls if c["path"] == "published_snapshot" and c["method"] == "POST"]
    assert len(posts) == 2 and all(c["params"] == SNAPSHOT_PARAMS for c in posts)

    response = api.delete(f"/api/clients/{client_id}/portal/publish")

    assert response.json() == {"configured": True, "published": {}}
    assert fake.calls[-1]["method"] == "DELETE" and fake.calls[-1]["params"] == {"id": f"eq.{client_id}"}


def test_a_client_with_no_upload_cannot_be_published(api, fake):
    empty = api.post("/api/clients", json={"name": "Empty"}).json()

    assert api.post(f"/api/clients/{empty['id']}/portal/publish").status_code == 404
    assert fake.calls == []


def test_errors_never_contain_the_key_or_the_url(api, client_id, fake):
    fake.fail_with = requests.ConnectionError(f"HTTPSConnectionPool(host='portal.test'): key={KEY}")

    response = api.post(f"/api/clients/{client_id}/portal/publish")

    assert response.status_code == 502
    assert KEY not in response.text and "portal.test" not in response.text


def test_a_refusal_from_the_portal_is_reported_as_a_bad_gateway(api, client_id, monkeypatch, fake):
    monkeypatch.setattr(requests, "request", lambda *a, **k: FakeResponse(401, {"message": f"bad key {KEY}"}))

    response = api.post(f"/api/clients/{client_id}/portal/publish")

    assert response.status_code == 502 and "HTTP 401" in response.json()["error"] and KEY not in response.text


def test_an_oversized_snapshot_is_refused(api, client_id, fake, monkeypatch):
    monkeypatch.setattr(portal, "MAX_PAYLOAD_BYTES", 1000)

    response = api.post(f"/api/clients/{client_id}/portal/publish")

    assert response.status_code == 413
    assert fake.calls == []  # the size is checked before anything is sent


def test_deleting_a_client_takes_it_off_the_portal_first(api, client_id, fake, catalog_session):
    assert api.delete(f"/api/clients/{client_id}").status_code == 200

    assert fake.calls[0]["method"] == "DELETE" and fake.calls[0]["params"] == {"id": f"eq.{client_id}"}
    assert catalog_session.get(Client, uuid.UUID(client_id)) is None


def test_if_the_portal_is_down_the_client_is_kept(api, client_id, fake):
    fake.fail_with = requests.ConnectionError("down")

    response = api.delete(f"/api/clients/{client_id}")

    assert response.status_code == 502 and "Not deleted" in response.json()["error"]
    assert api.get(f"/api/clients/{client_id}").status_code == 200  # still there: its online copy was not removed


def test_a_small_export_publishes_its_table(api, tmp_path, fake):
    created = api.post("/api/clients", json={"name": "Tiny"}).json()
    upload(api, created["id"], write_xlsx(tmp_path / "t.xlsx", SIMPLE_HEADERS, simple_rows()))

    api.post(f"/api/clients/{created['id']}/portal/publish")

    dashboard = next(r["payload"] for r in fake.calls[1]["body"] if r["kind"] == "dashboard")
    assert [r["Views"] for r in dashboard["rows"]] == [300, 200, 100]
