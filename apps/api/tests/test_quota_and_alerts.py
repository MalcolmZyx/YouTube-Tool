"""The quota counter, and the alerts about stored YouTube data that needs a manual refresh or delete."""
import uuid
from datetime import timedelta

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from studio_fixtures import ID_A, ID_B, ID_C, SIMPLE_HEADERS, simple_rows, write_xlsx

import deps
from app import app
from config import settings
from db.models import ApiUsage, VideoPublicMetadata, VideoTag
from db.session import get_session
from youtube import quota
from youtube.status import alerts, delete_public_data


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body


def video(video_id):
    return {"id": video_id, "snippet": {"description": "d", "tags": ["Retro"], "categoryId": "20"}}


@pytest.fixture
def api(catalog_session, monkeypatch):
    app.dependency_overrides[get_session] = lambda: catalog_session
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def client_id(api, tmp_path):
    created = api.post("/api/clients", json={"name": "Acme"}).json()
    path = write_xlsx(tmp_path / "Table data.xlsx", SIMPLE_HEADERS, simple_rows())
    with open(path, "rb") as fh:
        api.post(f"/api/clients/{created['id']}/uploads", files={"file": (path.name, fh.read())})
    return created["id"]


def enrich(api, client_id, monkeypatch, ids=(ID_A, ID_B, ID_C)):
    items = [video(i) for i in ids]
    monkeypatch.setattr(requests, "get", lambda url, params, timeout: FakeResponse(body={"items": items}))
    return api.post(f"/api/clients/{client_id}/enrich")


def age(session, days_left):
    """Make every stored row expire `days_left` days from now (negative: already expired)."""
    session.execute(update(VideoPublicMetadata).values(
        fetched_at=func.now() - timedelta(days=40), expires_at=func.now() + timedelta(days=days_left)))


# ── quota ───────────────────────────────────────────────────────────────────


def test_quota_starts_full_and_counts_what_is_spent(catalog_session):
    assert (quota.get_status(catalog_session).used_today, quota.get_status(catalog_session).remaining) == (0, 10_000)

    quota.record(catalog_session, 100)
    quota.record(catalog_session, 1)
    status = quota.get_status(catalog_session)

    assert (status.used_today, status.remaining, status.used_last_7_days) == (101, 9_899, 101)
    assert status.resets_at > catalog_session.scalar(select(func.now()))
    assert status.resets_at < catalog_session.scalar(select(func.now())) + timedelta(hours=25)


def test_the_week_total_includes_earlier_days_but_not_older_ones(catalog_session):
    quota.record(catalog_session, 5)
    today = catalog_session.scalar(select(ApiUsage.day))
    catalog_session.add_all([
        ApiUsage(day=today - timedelta(days=3), units=40), ApiUsage(day=today - timedelta(days=9), units=900),
    ])
    catalog_session.flush()

    status = quota.get_status(catalog_session)

    assert (status.used_today, status.used_last_7_days) == (5, 45)


def test_mark_exhausted_fills_the_day_but_never_lowers_it(catalog_session, monkeypatch):
    monkeypatch.setattr(settings, "youtube_daily_quota", 500)
    quota.record(catalog_session, 120)

    quota.mark_exhausted(catalog_session)

    assert quota.get_status(catalog_session).remaining == 0
    quota.record(catalog_session, 50)
    quota.mark_exhausted(catalog_session)
    assert catalog_session.scalar(select(ApiUsage.units)) == 550  # kept the higher figure


def test_quota_route(api):
    quota_before = api.get("/api/quota").json()
    assert (quota_before["limit"], quota_before["remaining"], quota_before["estimate"]) == (10_000, 10_000, True)


def test_enrich_spends_one_unit_per_fifty_videos(api, client_id, monkeypatch):
    assert enrich(api, client_id, monkeypatch).status_code == 200

    assert api.get("/api/quota").json()["used_today"] == 1  # 3 videos = 1 request = 1 unit
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("nothing was due"))
    api.post(f"/api/clients/{client_id}/enrich")
    assert api.get("/api/quota").json()["used_today"] == 1


def test_a_search_spends_a_hundred_units_and_a_failed_one_nothing(api, monkeypatch):
    monkeypatch.setattr(deps.researcher_svc, "search", lambda **kw: [
        {"video_id": ID_A, "title": "T", "url": "u", "channel": "c", "published_at": "2024-01-01", "views": 1,
         "likes": 0, "comment_count": 0, "tags": [], "thumbnail": "", "description": ""}])
    assert api.post("/api/researcher/search", json={"query": "x"}).status_code == 200
    assert api.get("/api/quota").json()["used_today"] == 101

    monkeypatch.setattr(deps.researcher_svc, "search", lambda **kw: [])
    api.post("/api/researcher/search", json={"query": "y"})
    assert api.get("/api/quota").json()["used_today"] == 201  # no results: the search only


def test_a_refusal_from_youtube_zeroes_what_is_left_and_stops_further_calls(api, client_id, monkeypatch):
    refusal = {"error": {"errors": [{"reason": "quotaExceeded"}]}}
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(403, refusal))

    assert api.post(f"/api/clients/{client_id}/enrich").status_code == 429
    assert api.get("/api/quota").json()["remaining"] == 0  # survived the error response's rollback

    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("called YouTube with no quota left"))
    blocked = api.post(f"/api/clients/{client_id}/enrich")
    assert blocked.status_code == 429 and "Not enough" in blocked.json()["error"]


# ── alerts ──────────────────────────────────────────────────────────────────


def test_fresh_data_raises_no_alert(api, client_id, monkeypatch):
    enrich(api, client_id, monkeypatch)

    assert api.get("/api/public-data/alerts").json() == []


def test_data_expiring_within_a_week_raises_a_warning(api, client_id, catalog_session, monkeypatch):
    enrich(api, client_id, monkeypatch)
    age(catalog_session, days_left=5)

    (alert,) = api.get("/api/public-data/alerts").json()

    assert (alert["client_name"], alert["level"]) == ("Acme", "expiring")
    assert (alert["expiring_soon"], alert["expired"]) == (3, 0)


def test_expired_data_is_an_alert_and_is_already_hidden_from_the_analyses(api, client_id, catalog_session, monkeypatch):
    enrich(api, client_id, monkeypatch)
    age(catalog_session, days_left=-2)

    (alert,) = api.get("/api/public-data/alerts").json()

    assert (alert["level"], alert["expired"]) == ("expired", 3)
    assert api.get(f"/api/clients/{client_id}/descriptions").json()["total"] == 0


def test_refreshing_clears_the_alert(api, client_id, catalog_session, monkeypatch):
    enrich(api, client_id, monkeypatch)
    age(catalog_session, days_left=2)
    assert len(api.get("/api/public-data/alerts").json()) == 1

    enrich(api, client_id, monkeypatch)  # the button the banner offers

    assert api.get("/api/public-data/alerts").json() == []


def test_deleting_public_data_clears_the_alert_and_keeps_the_export(api, client_id, catalog_session, monkeypatch):
    enrich(api, client_id, monkeypatch)
    age(catalog_session, days_left=2)

    response = api.delete(f"/api/clients/{client_id}/public-data")

    assert response.json() == {"deleted_videos": 3}
    assert api.get("/api/public-data/alerts").json() == []
    assert catalog_session.scalar(select(func.count()).select_from(VideoTag)) == 0
    assert api.get(f"/api/clients/{client_id}/dashboard").json()["rows"]  # the creator's figures are untouched
    assert api.delete(f"/api/clients/{uuid.uuid4()}/public-data").status_code == 404


def test_alerts_function_ignores_clients_without_stored_data(catalog_session):
    assert alerts(catalog_session) == []
    assert delete_public_data(catalog_session, uuid.uuid4()) == 0
    assert catalog_session.scalar(select(func.count()).select_from(VideoPublicMetadata)) == 0
