"""Public YouTube data: batched fetching, the 30-day store, purging, and the routes that use them."""
import uuid
from datetime import timedelta

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from studio_fixtures import ID_A, ID_B, ID_C, SIMPLE_HEADERS, simple_rows, write_xlsx

from app import app
from db.models import Client, Video, VideoPublicMetadata, VideoTag
from db.session import get_session
from youtube.__main__ import main
from youtube.client import QuotaExceeded, VideoInfo, YouTubeError, batches, fetch_videos
from youtube.store import purge_expired, refresh_client, videos_due


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


# ── the store ───────────────────────────────────────────────────────────────


@pytest.fixture
def videos(catalog_session):
    client = Client(name="Acme")
    catalog_session.add(client)
    catalog_session.flush()
    catalog_session.add_all(Video(client_id=client.id, youtube_video_id=v) for v in (ID_A, ID_B, ID_C))
    catalog_session.flush()
    return client.id


META = VideoPublicMetadata


def tags_of(session, youtube_id):
    query = select(VideoTag.tag).join(Video, Video.id == VideoTag.video_id).where(Video.youtube_video_id == youtube_id)
    return session.scalars(query).all()


def fake_fetch(available):
    def fetch(ids, key):
        return {i: VideoInfo(i, f"desc {i}", ["Retro ", "retro", "Pixel Art"], "20") for i in ids if i in available}
    return fetch


def test_refresh_stores_details_tags_normalised_and_marks_missing_videos(catalog_session, videos):
    result = refresh_client(catalog_session, videos, "KEY", fetch=fake_fetch({ID_A, ID_B}))

    assert (result.requested, result.stored, result.unavailable) == (3, 2, 1)
    states = dict(catalog_session.execute(
        select(Video.youtube_video_id, VideoPublicMetadata.availability).join(META, META.video_id == Video.id)
    ).all())
    assert states == {ID_A: "public", ID_B: "public", ID_C: "unavailable"}
    tags = tags_of(catalog_session, ID_A)
    assert sorted(tags) == ["pixel art", "retro"]  # lower-cased, trimmed, de-duplicated


def test_fresh_data_is_not_fetched_again_but_stale_or_forced_data_is(catalog_session, videos):
    refresh_client(catalog_session, videos, "KEY", fetch=fake_fetch({ID_A, ID_B, ID_C}))
    assert videos_due(catalog_session, videos) == []

    catalog_session.execute(update(VideoPublicMetadata).values(fetched_at=func.now() - timedelta(days=8)))
    assert len(videos_due(catalog_session, videos)) == 3
    catalog_session.execute(update(VideoPublicMetadata).values(fetched_at=func.now()))
    assert len(videos_due(catalog_session, videos, force=True)) == 3


def test_refreshing_renews_the_expiry_and_replaces_tags(catalog_session, videos):
    refresh_client(catalog_session, videos, "KEY", fetch=fake_fetch({ID_A}))
    catalog_session.execute(update(VideoPublicMetadata).values(
        fetched_at=func.now() - timedelta(days=29), expires_at=func.now() + timedelta(days=1)))

    def changed(ids, key):
        return {i: VideoInfo(i, "new", ["fresh tag"], "22") for i in ids}

    refresh_client(catalog_session, videos, "KEY", fetch=changed, force=True)

    expires_in = catalog_session.scalar(select(META.expires_at - func.now()).where(META.availability == "public"))
    assert expires_in > timedelta(days=29)
    assert catalog_session.scalars(select(VideoTag.tag).order_by(VideoTag.tag)).all() == ["fresh tag"] * 3


def test_expired_data_is_purged_with_its_tags_and_fresh_data_is_kept(catalog_session, videos):
    refresh_client(catalog_session, videos, "KEY", fetch=fake_fetch({ID_A, ID_B}))
    catalog_session.execute(update(VideoPublicMetadata).where(
        VideoPublicMetadata.video_id == select(Video.id).where(Video.youtube_video_id == ID_A).scalar_subquery()
    ).values(fetched_at=func.now() - timedelta(days=31), expires_at=func.now() - timedelta(days=1)))

    assert purge_expired(catalog_session) == 1

    left = catalog_session.scalars(select(Video.youtube_video_id).join(META, META.video_id == Video.id)).all()
    assert sorted(left) == [ID_B, ID_C]  # C keeps its (unexpired) 'unavailable' marker; A is gone
    assert tags_of(catalog_session, ID_A) == []
    assert catalog_session.scalar(select(func.count()).select_from(Video)) == 3  # the export's own data is untouched


def test_deleting_a_client_erases_its_public_data_too(catalog_session, videos):
    refresh_client(catalog_session, videos, "KEY", fetch=fake_fetch({ID_A, ID_B, ID_C}))

    catalog_session.delete(catalog_session.get(Client, videos))
    catalog_session.flush()

    assert catalog_session.scalar(select(func.count()).select_from(VideoPublicMetadata)) == 0
    assert catalog_session.scalar(select(func.count()).select_from(VideoTag)) == 0


# ── the routes and the command line ─────────────────────────────────────────


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


def test_expired_data_stops_appearing_in_analyses(api, client_id, catalog_session, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda url, params, timeout: FakeResponse(body={"items": [item(ID_A)]}))
    api.post(f"/api/clients/{client_id}/enrich")
    catalog_session.execute(update(VideoPublicMetadata).values(
        fetched_at=func.now() - timedelta(days=31), expires_at=func.now() - timedelta(days=1)))

    assert api.get(f"/api/clients/{client_id}/descriptions").json()["total"] == 0  # hidden even before the purge runs


def test_enrich_needs_a_key_and_reports_failures(api, client_id, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(500, {}))
    assert api.post(f"/api/clients/{client_id}/enrich").status_code == 502
    monkeypatch.setenv("YOUTUBE_API_KEY", "")
    assert api.post(f"/api/clients/{client_id}/enrich").status_code == 400
    assert api.post(f"/api/clients/{uuid.uuid4()}/enrich").status_code in (400, 404)


def test_purge_command(db_engine, capsys):
    assert main(["purge"], engine=db_engine) == 0
    assert "Purged public data for" in capsys.readouterr().out


def test_refresh_command_needs_a_key(db_engine, monkeypatch, capsys):
    monkeypatch.setenv("YOUTUBE_API_KEY", "")

    assert main(["refresh", str(uuid.uuid4())], engine=db_engine) == 1
    assert "not set" in capsys.readouterr().out
