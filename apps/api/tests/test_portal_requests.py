"""Requests, permissions and preferences that clients create in the portal, as seen from the admin app."""
import json
import re
import uuid

import pytest
import requests
from fastapi.testclient import TestClient

from app import app
from config import settings
from db.session import get_session

KEY = "service-key-SECRET-123"


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body if body is not None else []

    def json(self):
        return self._body


class FakePortal:
    """In-memory stand-in for the portal tables the admin app touches."""

    def __init__(self):
        self.requests, self.permissions, self.preferences, self.calls = [], [], {}, []
        self.fail_with = None

    def __call__(self, method, url, params=None, headers=None, data=None, timeout=None):
        if self.fail_with:
            raise self.fail_with
        table = url.split("/rest/v1/")[1]
        body = json.loads(data) if data else None
        params = params or {}
        self.calls.append((method, table, params, body))
        if table == "service_request":
            if method == "GET":
                rows = self.requests
                if "status" in params:
                    allowed = re.findall(r"[a-z]+", params["status"].removeprefix("in."))
                    rows = [r for r in rows if r["status"] in allowed]
                return FakeResponse(body=rows)
            if method == "PATCH":
                wanted = int(params["id"].removeprefix("eq."))
                hit = [r for r in self.requests if r["id"] == wanted]
                for r in hit:
                    r.update(body)
                return FakeResponse(body=hit)
        if table == "client_permission":
            client = params.get("client_id", "").removeprefix("eq.")
            if method == "GET":
                return FakeResponse(body=[p for p in self.permissions if p["client_id"] == client])
            if method == "POST":
                self.permissions = [p for p in self.permissions
                                    if (p["client_id"], p["feature"]) != (body["client_id"], body["feature"])]
                self.permissions.append(body)
                return FakeResponse(201)
            if method == "DELETE":
                feature = params["feature"].removeprefix("eq.")
                self.permissions = [p for p in self.permissions if (p["client_id"], p["feature"]) != (client, feature)]
                return FakeResponse(204)
        if table == "dashboard_preference" and method == "GET":
            client = params["client_id"].removeprefix("eq.")
            return FakeResponse(body=[self.preferences[client]] if client in self.preferences else [])
        raise AssertionError(f"unexpected portal call {method} {table}")


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


@pytest.fixture
def client_id(api):
    return api.post("/api/clients", json={"name": "Acme"}).json()["id"]


def request_row(rid, client, status="requested", note="please", kind="research"):
    return {"id": rid, "client_id": client, "type": kind, "note": note, "status": status,
            "created_at": "2026-10-14T10:00:00+00:00", "updated_at": "2026-10-14T10:00:00+00:00"}


def test_requests_are_listed_with_the_local_client_name(api, client_id, fake):
    ghost = str(uuid.uuid4())
    fake.requests = [request_row(1, client_id), request_row(2, ghost, note="from a deleted client")]

    rows = api.get("/api/portal/requests").json()

    assert [(r["id"], r["client_name"]) for r in rows] == [(1, "Acme"), (2, None)]


def test_open_only_hides_declined_and_finished_requests(api, client_id, fake):
    fake.requests = [request_row(1, client_id, "requested"), request_row(2, client_id, "approved"),
                     request_row(3, client_id, "declined"), request_row(4, client_id, "done")]

    assert {r["id"] for r in api.get("/api/portal/requests?open_only=true").json()} == {1, 2}
    assert len(api.get("/api/portal/requests").json()) == 4


def test_a_request_can_be_approved_declined_and_finished(api, client_id, fake):
    fake.requests = [request_row(7, client_id)]

    response = api.put("/api/portal/requests/7", json={"status": "approved"})

    assert response.status_code == 200 and response.json()["status"] == "approved"
    assert fake.requests[0]["status"] == "approved" and "updated_at" in fake.calls[-1][3]
    assert api.put("/api/portal/requests/7", json={"status": "done"}).json()["status"] == "done"


@pytest.mark.parametrize("body", [{"status": "nonsense"}, {}, {"status": "approved; drop table"}])
def test_an_invalid_status_is_rejected_before_reaching_the_portal(api, fake, body):
    assert api.put("/api/portal/requests/1", json=body).status_code == 422
    assert fake.calls == []


def test_an_unknown_request_is_a_404(api, fake):
    assert api.put("/api/portal/requests/999", json={"status": "done"}).status_code == 404


def test_without_the_portal_configured_the_routes_say_so(api, client_id):
    assert api.get("/api/portal/requests").status_code == 503
    assert api.get(f"/api/clients/{client_id}/portal/permissions").status_code == 503


def test_a_client_note_is_returned_as_plain_text(api, client_id, fake):
    hostile = '<script>alert(1)</script>"; drop table x; --'
    fake.requests = [request_row(1, client_id, note=hostile)]

    assert api.get("/api/portal/requests").json()[0]["note"] == hostile  # stored and shown as text, never run


def test_permissions_can_be_granted_listed_changed_and_removed(api, client_id, fake):
    url = f"/api/clients/{client_id}/portal/permissions"

    granted = api.put(f"{url}/research", json={"status": "granted", "quota": 50, "expires_in_days": 30}).json()

    assert [(p["feature"], p["status"], p["quota"]) for p in granted] == [("research", "granted", 50)]
    assert granted[0]["expires_at"] is not None
    changed = api.put(f"{url}/research", json={"status": "expired"}).json()
    assert [(p["status"], p["quota"], p["expires_at"]) for p in changed] == [("expired", None, None)]
    assert api.delete(f"{url}/research").json() == []


@pytest.mark.parametrize("feature", ["Research", "has space", "x" * 101, "a;b"])
def test_odd_feature_names_are_rejected(api, client_id, fake, feature):
    response = api.put(f"/api/clients/{client_id}/portal/permissions/{feature}", json={"status": "granted"})

    assert response.status_code in (404, 422) and fake.calls == []


@pytest.mark.parametrize("body", [{"status": "granted", "quota": -1}, {"status": "granted", "expires_in_days": 0},
                                  {"status": "maybe"}])
def test_invalid_permission_values_are_rejected(api, client_id, fake, body):
    assert api.put(f"/api/clients/{client_id}/portal/permissions/research", json=body).status_code == 422


def test_permissions_only_for_clients_that_exist_here(api, fake):
    assert api.get(f"/api/clients/{uuid.uuid4()}/portal/permissions").status_code == 404
    assert fake.calls == []


def test_preferences_are_read_and_default_to_empty(api, client_id, fake):
    assert api.get(f"/api/clients/{client_id}/portal/preferences").json() == {"focus": {}, "updated_at": None}
    fake.preferences[client_id] = {"focus": {"areas": ["retention"]}, "updated_at": "2026-10-14T10:00:00+00:00"}

    assert api.get(f"/api/clients/{client_id}/portal/preferences").json()["focus"] == {"areas": ["retention"]}


def test_portal_failures_never_leak_the_key(api, client_id, fake):
    fake.fail_with = requests.ConnectionError(f"boom key={KEY} host=portal.test")

    for response in (api.get("/api/portal/requests"), api.get(f"/api/clients/{client_id}/portal/permissions")):
        assert response.status_code == 502 and KEY not in response.text and "portal.test" not in response.text
