"""Public YouTube data: batched fetching, the 30-day store, purging, and the routes that use them."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import requests
from fastapi.testclient import TestClient
from studio_fixtures import ID_A, ID_B, ID_C, SIMPLE_HEADERS, simple_rows, write_xlsx

from app import app
from db.models import Client, Video
from db.session import get_session
from youtube import store
from youtube.__main__ import main
from youtube.client import QuotaExceeded, VideoInfo, YouTubeError, batches, fetch_videos
from youtube.store import delete_client_data, load_public_data, purge_expired, refresh_client, videos_due


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body


def item(video_id, tags=("Pixel Art", "  retro "), description="About #retro https://x.y"):
    return {"id": video_id, "snippet": {
        "description": description, "tags": list(tags), "categoryId": "20", "publishedAt": "2024-01-01T10:00:00Z",
        "thumbnails": {"default": {"url": "http://t/d.jpg"}, "high": {"url": "http://t/h.jpg"}},
    }}


# ── the client ──────────────────────────────────────────────────────────────


def test_ids_are_sent_fifty_at_a_time():
    assert [len(b) for b in batches([str(i) for i in range(120)])] == [50, 50, 20]


def test_fetch_parses_details_and_omits_unavailable_videos():
    calls = []

    def get(url, params, timeout):
        calls.append(params)
        return FakeResponse(body={"items": [item("a" * 11)]})

    found = fetch_videos(["a" * 11, "b" * 11], "KEY", get=get)

    assert list(found) == ["a" * 11]  # the second video came back absent: private, deleted or unknown
    info = found["a" * 11]
    assert (info.category_id, info.thumbnail_url) == ("20", "http://t/h.jpg")  # the best size available
    assert info.published_at.year == 2024 and calls[0]["part"] == "snippet"


def test_fetch_makes_one_request_per_fifty_videos():
    calls = []

    def get(url, params, timeout):
        calls.append(params["id"].count(",") + 1)
        return FakeResponse(body={"items": []})

    fetch_videos([f"{i:011d}" for i in range(120)], "KEY", get=get)

    assert calls == [50, 50, 20]


def test_quota_and_key_errors_are_distinguished():
    quota = {"error": {"errors": [{"reason": "quotaExceeded"}]}}
    bad_key = {"error": {"errors": [{"reason": "keyInvalid"}]}}

    with pytest.raises(QuotaExceeded):
        fetch_videos(["a" * 11], "KEY", get=lambda *a, **k: FakeResponse(403, quota))
    with pytest.raises(YouTubeError, match="rejected the key"):
        fetch_videos(["a" * 11], "KEY", get=lambda *a, **k: FakeResponse(400, bad_key))
    with pytest.raises(YouTubeError):
        fetch_videos(["a" * 11], "KEY", get=lambda *a, **k: FakeResponse(500, "not json"))


def test_a_network_error_never_leaks_the_key():
    def get(*a, **k):
        raise requests.ConnectionError("failed: https://www.googleapis.com/youtube/v3/videos?key=SECRET123")

    with pytest.raises(YouTubeError) as caught:
        fetch_videos(["a" * 11], "SECRET123", get=get)

    assert "SECRET123" not in str(caught.value)


# ── the store (MongoDB) ─────────────────────────────────────────────────────


@pytest.fixture
def videos(catalog_session):
    client = Client(name="Acme")
    catalog_session.add(client)
    catalog_session.flush()
    catalog_session.add_all(Video(client_id=client.id, youtube_video_id=v) for v in (ID_A, ID_B, ID_C))
    catalog_session.flush()
    return client.id


def snippet(video_id, description=None, tags=("Retro ", "retro", "Pixel Art")):
    return {"description": description or f"desc {video_id}", "tags": list(tags), "categoryId": "20",
            "thumbnails": {"high": {"url": "http://t/h.jpg"}}}


def fake_fetch(available):
    def fetch(ids, key):
        return {i: VideoInfo(i, "d", [], "20", snippet=snippet(i)) for i in ids if i in available}
    return fetch


def now():
    return datetime.now(UTC)


def test_the_thirty_day_rule_is_a_database_index(mongo):
    store.collection()  # creates the indexes

    ttl = mongo.index_information()["ttl_expires_at"]

    assert ttl["key"] == [("expires_at", 1)] and ttl["expireAfterSeconds"] == 0  # delete when expires_at passes


def test_refresh_keeps_the_raw_snippet_and_derives_tags_when_read(mongo, catalog_session, videos):
    result = refresh_client(catalog_session, videos, "KEY", fetch=fake_fetch({ID_A, ID_B}))

    assert (result.requested, result.stored, result.unavailable) == (3, 2, 1)
    documents = {d["youtube_video_id"]: d for d in mongo.find()}
    assert {k: d["availability"] for k, d in documents.items()} == {ID_A: "public", ID_B: "public", ID_C: "unavailable"}
    assert documents[ID_A]["raw"] == snippet(ID_A)  # exactly what the API returned, not a derived copy
    assert documents[ID_C]["raw"] is None
    assert documents[ID_A]["expires_at"] - documents[ID_A]["fetched_at"] == timedelta(days=30)
    public = load_public_data(videos)
    assert set(public) == {ID_A, ID_B} and public[ID_A]["tags"] == ["pixel art", "retro"]  # lower-cased, de-duplicated
    assert public[ID_A]["thumbnail_url"] == "http://t/h.jpg"


def test_fresh_data_is_not_fetched_again_but_stale_or_forced_data_is(mongo, catalog_session, videos):
    refresh_client(catalog_session, videos, "KEY", fetch=fake_fetch({ID_A, ID_B, ID_C}))
    assert videos_due(catalog_session, videos) == []

    mongo.update_many({}, {"$set": {"fetched_at": now() - timedelta(days=8)}})
    assert len(videos_due(catalog_session, videos)) == 3
    mongo.update_many({}, {"$set": {"fetched_at": now()}})
    assert len(videos_due(catalog_session, videos, force=True)) == 3


def test_refreshing_renews_the_expiry_and_replaces_the_document(mongo, catalog_session, videos):
    refresh_client(catalog_session, videos, "KEY", fetch=fake_fetch({ID_A}))
    mongo.update_many({}, {"$set": {"fetched_at": now() - timedelta(days=29), "expires_at": now() + timedelta(days=1)}})

    def changed(ids, key):
        return {i: VideoInfo(i, "d", [], "22", snippet=snippet(i, "new", ["fresh tag"])) for i in ids}

    refresh_client(catalog_session, videos, "KEY", fetch=changed, force=True)

    assert mongo.count_documents({}) == 3  # replaced in place, not duplicated
    assert all(d["expires_at"] > now() + timedelta(days=29) for d in mongo.find())
    assert load_public_data(videos)[ID_A]["tags"] == ["fresh tag"]


def test_expired_data_is_hidden_at_once_and_purged_on_demand(mongo, catalog_session, videos):
    refresh_client(catalog_session, videos, "KEY", fetch=fake_fetch({ID_A, ID_B}))
    mongo.update_one({"youtube_video_id": ID_A}, {"$set": {"expires_at": now() - timedelta(days=1)}})

    assert set(load_public_data(videos)) == {ID_B}  # hidden even though MongoDB's own monitor has not run yet
    assert purge_expired() == 1

    assert sorted(d["youtube_video_id"] for d in mongo.find()) == [ID_B, ID_C]  # C keeps its 'unavailable' marker
    assert catalog_session.get(Client, videos) is not None  # the creator's own data is untouched


def test_one_clients_data_is_never_another_clients(mongo, catalog_session, videos):
    other = Client(name="Other")
    catalog_session.add(other)
    catalog_session.flush()
    catalog_session.add(Video(client_id=other.id, youtube_video_id=ID_A))
    catalog_session.flush()
    refresh_client(catalog_session, videos, "KEY", fetch=fake_fetch({ID_A, ID_B, ID_C}))
    refresh_client(catalog_session, other.id, "KEY", fetch=fake_fetch({ID_A}))

    assert mongo.count_documents({}) == 4  # the same YouTube video under two clients is two documents
    assert delete_client_data(videos) == 3
    assert set(load_public_data(other.id)) == {ID_A}


def test_the_store_says_so_when_it_is_not_configured(catalog_session, videos, monkeypatch):
    monkeypatch.setattr(store.settings, "mongo_url", "")

    with pytest.raises(store.StoreNotConfigured):
        refresh_client(catalog_session, videos, "KEY", fetch=fake_fetch({ID_A}))
    assert store.is_configured() is False


# ── the routes and the command line ─────────────────────────────────────────


@pytest.fixture
def api(catalog_session, monkeypatch, mongo):
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


def test_enrich_route_feeds_keywords_and_descriptions(api, client_id, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda url, params, timeout: FakeResponse(
        body={"items": [item(ID_A), item(ID_B, tags=("retro",))]}))

    result = api.post(f"/api/clients/{client_id}/enrich").json()

    assert result == {"requested": 3, "stored": 2, "unavailable": 1}
    tags = {t["tag"] for t in api.get(f"/api/clients/{client_id}/keywords/weighted").json()["tags"]}
    assert tags == {"pixel art", "retro"}
    descriptions = api.get(f"/api/clients/{client_id}/descriptions").json()
    assert descriptions["total"] == 2 and descriptions["videos"][0]["has_hashtags"] is True
    # a second call has nothing due, so makes no request
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("fetched data that was still fresh"))
    assert api.post(f"/api/clients/{client_id}/enrich").json()["requested"] == 0


def test_expired_data_stops_appearing_in_analyses(api, client_id, mongo, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda url, params, timeout: FakeResponse(body={"items": [item(ID_A)]}))
    api.post(f"/api/clients/{client_id}/enrich")
    mongo.update_many({}, {"$set": {"expires_at": now() - timedelta(days=1)}})

    assert api.get(f"/api/clients/{client_id}/descriptions").json()["total"] == 0  # hidden before MongoDB removes it


def test_deleting_a_client_erases_its_public_data_too(api, client_id, mongo, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda url, params, timeout: FakeResponse(body={"items": [item(ID_A)]}))
    api.post(f"/api/clients/{client_id}/enrich")
    assert mongo.count_documents({}) == 3

    assert api.delete(f"/api/clients/{client_id}").status_code == 200

    assert mongo.count_documents({}) == 0  # deletion on request is prompt: no copy is left behind


def test_if_the_store_is_down_the_client_is_kept(api, client_id, monkeypatch):
    def down():
        raise store.StoreError("Could not reach MongoDB (ServerSelectionTimeoutError).")

    monkeypatch.setattr(store, "collection", down)

    response = api.delete(f"/api/clients/{client_id}")

    assert response.status_code == 502 and "Not deleted" in response.json()["error"]
    assert api.get(f"/api/clients/{client_id}").status_code == 200


def test_the_dashboard_still_works_when_the_store_is_down(api, client_id, monkeypatch):
    def down():
        raise store.StoreError("down")

    monkeypatch.setattr(store, "collection", down)

    assert api.get(f"/api/clients/{client_id}/dashboard").status_code == 200  # only the enrichment is missing


def test_enrich_needs_a_key_and_reports_failures(api, client_id, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(500, {}))
    assert api.post(f"/api/clients/{client_id}/enrich").status_code == 502
    monkeypatch.setenv("YOUTUBE_API_KEY", "")
    assert api.post(f"/api/clients/{client_id}/enrich").status_code == 400
    assert api.post(f"/api/clients/{uuid.uuid4()}/enrich").status_code in (400, 404)


def test_enrich_without_mongodb_configured_is_a_clear_503(api, client_id, monkeypatch):
    monkeypatch.setattr(store.settings, "mongo_url", "")

    response = api.post(f"/api/clients/{client_id}/enrich")

    assert response.status_code == 503 and "MONGO_URL" in response.json()["error"]


def test_purge_command(mongo, db_engine, capsys):
    assert main(["purge"], engine=db_engine) == 0
    assert "Purged 0 expired documents." in capsys.readouterr().out


def test_purge_command_says_when_the_store_is_not_configured(db_engine, monkeypatch, capsys):
    monkeypatch.setattr(store.settings, "mongo_url", "")

    assert main(["purge"], engine=db_engine) == 1
    assert "not configured" in capsys.readouterr().out


def test_refresh_command_needs_a_key(db_engine, monkeypatch, capsys):
    monkeypatch.setenv("YOUTUBE_API_KEY", "")

    assert main(["refresh", str(uuid.uuid4())], engine=db_engine) == 1
    assert "not set" in capsys.readouterr().out
