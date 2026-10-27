"""The comment labeling queue, end to end: MongoDB for the comments, Postgres for the labels."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import app
from config import settings
from db.models import CommentLabel
from db.session import get_session
from labeling.stats import wilson_interval
from youtube.store import utcnow


@pytest.fixture
def api(db_session):
    app.dependency_overrides[get_session] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def mongo_db(mongo):
    return mongo.database


def comment(cid, video="v1", text=None, **extra):
    now = utcnow()
    return {
        "_id": cid, "comment_id": cid, "video_id": video, "is_reply": False, "parent_id": None,
        "text": text or f"text of {cid}", "like_count": 3, "reply_count": 0, "published_at": now - timedelta(days=2),
        "updated_at": now, "author_hash": None, "lang": "en", "lang_prob": 0.99,
        "stratum": {"category_id": "22", "view_band": "mid", "subscriber_band": "small", "age_band": "new",
                    "sampling": "random"},
        "fetched_at": now, "expires_at": now + timedelta(days=29), **extra,
    }


def seed(mongo_db, *docs, videos=("v1",)):
    mongo_db["youtube_comment"].insert_many(docs)
    for video in videos:
        mongo_db["youtube_crawl_video"].replace_one(
            {"_id": video}, {"_id": video, "video_id": video, "title": f"Title of {video}"}, upsert=True)


def rows(session):
    return {r.comment_id: r for r in session.scalars(select(CommentLabel))}


def label(api, cid, decision, **extra):
    return api.post("/api/labeling/labels", json={"comment_id": cid, "decision": decision, **extra})


def queue_ids(api, **params):
    response = api.get("/api/labeling/queue", params=params)
    assert response.status_code == 200, response.text
    return [item["comment_id"] for item in response.json()["items"]]


# ── the queue ───────────────────────────────────────────────────────────────


def test_queue_items_carry_what_the_page_needs(api, mongo_db):
    seed(mongo_db, comment("a", text="<b>too long</b>"))
    body = api.get("/api/labeling/queue").json()
    assert body["mode"] == "random"
    item = body["items"][0]
    assert item["comment_id"] == "a"
    assert item["text"] == "<b>too long</b>"  # plain text, returned untouched
    assert item["video_title"] == "Title of v1"
    assert item["like_count"] == 3
    assert item["stratum"]["category_id"] == "22"
    assert item["published_at"]


def test_queue_leaves_out_replies_expired_and_decided_comments(api, mongo_db):
    expired = utcnow() - timedelta(minutes=1)
    seed(
        mongo_db, comment("open1"), comment("open2"), comment("reply", is_reply=True),
        comment("old", expires_at=expired), comment("done"), comment("dropped"),
    )
    assert label(api, "done", "not_constructive").status_code == 200
    assert label(api, "dropped", "discard").status_code == 200
    assert sorted(queue_ids(api)) == ["open1", "open2"]


def test_skipped_comments_come_back_only_after_the_never_seen_ones(api, mongo_db):
    seed(mongo_db, *(comment(f"c{i}") for i in range(6)))
    assert label(api, "c0", "skip").status_code == 200
    for _ in range(10):  # random order, so repeat
        ids = queue_ids(api, count=6)
        assert len(ids) == 6
        assert ids[-1] == "c0"
        assert "c0" not in ids[:-1]


def test_a_queue_of_only_skipped_comments_is_still_served(api, mongo_db):
    seed(mongo_db, comment("a"), comment("b"))
    label(api, "a", "skip")
    label(api, "b", "skip")
    assert sorted(queue_ids(api)) == ["a", "b"]


def test_queue_does_not_put_one_video_in_a_row(api, mongo_db):
    videos = ("v1", "v2", "v3")
    seed(mongo_db, *(comment(f"{v}-{i}", video=v) for v in videos for i in range(12)), videos=videos)
    for _ in range(20):
        items = api.get("/api/labeling/queue", params={"count": 8}).json()["items"]
        assert len(items) == 8
        titles = [i["video_title"] for i in items]
        assert all(a != b for a, b in zip(titles, titles[1:], strict=False)), titles


def test_queue_size_and_mode_are_validated(api, mongo_db):
    seed(mongo_db, *(comment(f"c{i}") for i in range(12)))
    assert len(queue_ids(api)) == 8  # the default
    assert len(queue_ids(api, count=3)) == 3
    for params in ({"count": 0}, {"count": 51}, {"mode": "enriched"}):
        response = api.get("/api/labeling/queue", params=params)
        assert response.status_code == 422
        assert "error" in response.json()


def test_empty_pool_gives_an_empty_queue(api, mongo_db):
    assert api.get("/api/labeling/queue").json()["items"] == []


def test_unconfigured_mongodb_is_reported_in_the_usual_shape(api, monkeypatch):
    monkeypatch.setattr(settings, "mongo_url", "")
    response = api.get("/api/labeling/queue")
    assert response.status_code == 503
    assert "not configured" in response.json()["error"]


# ── decisions ───────────────────────────────────────────────────────────────


def test_constructive_keeps_the_text_and_its_context(api, mongo_db, db_session):
    seed(mongo_db, comment("a", text="music drowns out your voice"))
    response = label(api, "a", "constructive", depth="specific", aspects=["audio", "pacing", "audio"])
    assert response.status_code == 200, response.text
    row = rows(db_session)["a"]
    assert (row.status, row.depth, row.aspects) == ("constructive", "specific", ["audio", "pacing"])
    assert row.text == "music drowns out your voice"
    assert (row.video_id, row.video_title, row.like_count) == ("v1", "Title of v1", 3)
    assert row.stratum["category_id"] == "22"
    assert row.published_at is not None
    assert row.queue_mode == "random"


def test_not_constructive_keeps_the_text_without_tags(api, mongo_db, db_session):
    seed(mongo_db, comment("a", text="great video"))
    assert label(api, "a", "not_constructive").status_code == 200
    row = rows(db_session)["a"]
    assert (row.status, row.depth, row.aspects, row.text) == ("not_constructive", None, [], "great video")


def test_discard_and_skip_keep_no_text(api, mongo_db, db_session):
    seed(mongo_db, comment("a"), comment("b"))
    assert label(api, "a", "discard").status_code == 200
    assert label(api, "b", "skip").status_code == 200
    saved = rows(db_session)
    for cid, status in (("a", "discarded"), ("b", "skipped")):
        row = saved[cid]
        assert row.status == status
        assert (row.text, row.video_id, row.video_title, row.stratum, row.like_count, row.published_at) == (None,) * 6


def test_the_response_has_fresh_stats_and_the_next_comment(api, mongo_db):
    seed(mongo_db, comment("a"), comment("b"))
    body = label(api, "a", "constructive").json()
    assert body["stats"]["labeled_total"] == 1
    assert body["stats"]["remaining"] == 1
    assert body["next"]["comment_id"] == "b"
    assert label(api, "b", "not_constructive").json()["next"] is None


def test_skipping_the_last_comment_does_not_serve_it_again(api, mongo_db):
    seed(mongo_db, comment("a"))
    assert label(api, "a", "skip").json()["next"] is None


@pytest.mark.parametrize("body", [
    {"decision": "not_constructive", "depth": "basic"},
    {"decision": "discard", "aspects": ["audio"]},
    {"decision": "skip", "depth": "basic"},
    {"decision": "constructive", "aspects": ["lighting"]},
    {"decision": "constructive", "depth": "expert"},
    {"decision": "maybe"},
])
def test_invalid_tags_and_decisions_are_rejected(api, mongo_db, db_session, body):
    seed(mongo_db, comment("a"))
    response = api.post("/api/labeling/labels", json={"comment_id": "a", **body})
    assert response.status_code == 422
    assert "error" in response.json()
    assert rows(db_session) == {}


def test_tags_are_optional_and_depth_alone_is_fine(api, mongo_db, db_session):
    seed(mongo_db, comment("a"), comment("b"))
    assert label(api, "a", "constructive").status_code == 200
    assert label(api, "b", "constructive", depth="basic").status_code == 200
    saved = rows(db_session)
    assert (saved["a"].depth, saved["a"].aspects) == (None, [])
    assert (saved["b"].depth, saved["b"].aspects) == ("basic", [])


def test_the_database_refuses_inconsistent_rows(db_session):
    from sqlalchemy.exc import IntegrityError

    bad = [
        CommentLabel(comment_id="x", status="not_constructive", text="t", depth="basic", queue_mode="random"),
        CommentLabel(comment_id="x", status="constructive", text=None, queue_mode="random"),
        CommentLabel(comment_id="x", status="discarded", text="kept", queue_mode="random"),
        CommentLabel(comment_id="x", status="constructive", text="t", aspects=["lighting"], queue_mode="random"),
        CommentLabel(comment_id="x", status="maybe", queue_mode="random"),
    ]
    for row in bad:
        with pytest.raises(IntegrityError), db_session.begin_nested():
            db_session.add(row)
            db_session.flush()
        db_session.expunge_all()


def test_relabeling_replaces_the_label_and_repeating_it_changes_nothing(api, mongo_db, db_session):
    seed(mongo_db, comment("a"))
    label(api, "a", "constructive", depth="basic", aspects=["audio"])
    first = rows(db_session)["a"]
    stamp = first.updated_at

    label(api, "a", "constructive", depth="basic", aspects=["audio"])  # a double click
    assert rows(db_session)["a"].updated_at == stamp
    assert rows(db_session)["a"].previous is None

    label(api, "a", "not_constructive")
    row = rows(db_session)["a"]
    assert (row.status, row.depth, row.aspects) == ("not_constructive", None, [])
    assert len(rows(db_session)) == 1


def test_a_label_can_change_after_the_comment_has_expired_from_mongodb(api, mongo_db, db_session):
    seed(mongo_db, comment("a", text="kept forever"))
    label(api, "a", "constructive")
    mongo_db["youtube_comment"].delete_many({})
    assert label(api, "a", "not_constructive").status_code == 200
    assert rows(db_session)["a"].text == "kept forever"
    assert label(api, "a", "discard").status_code == 200
    assert rows(db_session)["a"].text is None


# ── a comment that vanishes ─────────────────────────────────────────────────


@pytest.mark.parametrize("decision", ["constructive", "not_constructive", "discard", "skip"])
def test_a_comment_that_vanished_between_queue_and_submit_gives_404(api, mongo_db, db_session, decision):
    seed(mongo_db, comment("a"))
    assert queue_ids(api) == ["a"]
    mongo_db["youtube_comment"].delete_many({})  # the TTL monitor took it
    response = label(api, "a", decision)
    assert response.status_code == 404
    assert "expired" in response.json()["error"]
    assert rows(db_session) == {}


def test_an_expired_comment_that_mongodb_has_not_yet_removed_counts_as_gone(api, mongo_db, db_session):
    seed(mongo_db, comment("a", expires_at=utcnow() - timedelta(seconds=5)))
    assert label(api, "a", "not_constructive").status_code == 404


def test_a_skipped_comment_that_expired_cannot_be_kept_but_can_be_discarded(api, mongo_db, db_session):
    seed(mongo_db, comment("a"))
    label(api, "a", "skip")
    mongo_db["youtube_comment"].delete_many({})
    assert label(api, "a", "constructive").status_code == 404
    assert rows(db_session)["a"].status == "skipped"
    assert label(api, "a", "discard").status_code == 200


# ── undo ────────────────────────────────────────────────────────────────────


def test_undo_with_nothing_to_undo_is_a_404(api, mongo_db):
    response = api.post("/api/labeling/labels/undo")
    assert response.status_code == 404
    assert response.json() == {"error": "Nothing to undo."}


def test_undo_makes_a_first_label_unlabeled_again(api, mongo_db, db_session):
    seed(mongo_db, comment("a"), comment("b"))
    label(api, "a", "constructive", depth="basic")
    body = api.post("/api/labeling/labels/undo").json()
    assert rows(db_session) == {}
    assert body["undone"]["comment_id"] == "a"
    assert body["undone"]["text"] == "text of a"
    assert body["stats"]["labeled_total"] == 0
    assert "a" in queue_ids(api)


def test_undo_walks_back_through_the_latest_actions_in_order(api, mongo_db, db_session):
    seed(mongo_db, comment("a"), comment("b"))
    label(api, "a", "not_constructive")
    label(api, "b", "discard")
    assert api.post("/api/labeling/labels/undo").json()["undone"]["comment_id"] == "b"
    assert set(rows(db_session)) == {"a"}
    assert api.post("/api/labeling/labels/undo").json()["undone"]["comment_id"] == "a"
    assert rows(db_session) == {}


def test_undo_of_a_relabel_restores_the_earlier_label(api, mongo_db, db_session):
    seed(mongo_db, comment("a", text="the original"))
    label(api, "a", "constructive", depth="specific", aspects=["audio"])
    label(api, "a", "discard")
    assert rows(db_session)["a"].text is None

    body = api.post("/api/labeling/labels/undo").json()
    row = rows(db_session)["a"]
    assert (row.status, row.depth, row.aspects, row.text) == ("constructive", "specific", ["audio"], "the original")
    assert row.previous is None
    assert body["undone"]["comment_id"] == "a"
    assert body["stats"]["counts"]["constructive"] == 1

    api.post("/api/labeling/labels/undo")  # a second undo removes the first label
    assert rows(db_session) == {}


def test_undoing_a_discard_of_an_expired_comment_has_nothing_to_show(api, mongo_db, db_session):
    seed(mongo_db, comment("a"))
    label(api, "a", "discard")
    mongo_db["youtube_comment"].delete_many({})
    body = api.post("/api/labeling/labels/undo").json()
    assert body["undone"] is None
    assert rows(db_session) == {}


# ── stats ───────────────────────────────────────────────────────────────────


def test_wilson_interval_matches_hand_computed_values():
    # 3 of 10: centre (0.3 + 1.96^2/20) / (1 + 1.96^2/10) = 0.35553, half-width 0.24772
    low, high = wilson_interval(3, 10)
    assert low == pytest.approx(0.1078, abs=5e-4)
    assert high == pytest.approx(0.6032, abs=5e-4)
    # 0 of 10: the textbook interval would collapse to 0; Wilson keeps an upper bound of 1.96^2 / (10 + 1.96^2)
    low, high = wilson_interval(0, 10)
    assert low == 0
    assert high == pytest.approx(3.8416 / 13.8416, abs=1e-4)
    # 50 of 100
    low, high = wilson_interval(50, 100)
    assert (low, high) == (pytest.approx(0.4038, abs=5e-4), pytest.approx(0.5962, abs=5e-4))
    assert wilson_interval(10, 10)[1] == 1
    assert wilson_interval(0, 0) is None


def test_stats_on_an_empty_database(api, mongo_db):
    body = api.get("/api/labeling/stats").json()
    assert body["counts"] == {"constructive": 0, "not_constructive": 0, "discarded": 0, "skipped": 0}
    assert body["labeled_total"] == 0
    assert body["remaining"] == 0
    assert body["prevalence"]["share"] is None
    assert body["prevalence"]["low"] is None


def test_stats_count_decisions_tags_and_categories(api, mongo_db):
    other = {"stratum": {"category_id": "10"}}
    seed(
        mongo_db,
        comment("c1"), comment("c2"), comment("c3"), comment("n1", **other), comment("n2"), comment("n3"),
        comment("n4"), comment("x"), comment("s"), comment("open1"), comment("open2"),
    )
    label(api, "c1", "constructive", depth="basic", aspects=["audio"])
    label(api, "c2", "constructive", depth="advanced", aspects=["audio", "pacing"])
    label(api, "c3", "constructive")
    for cid in ("n1", "n2", "n3", "n4"):
        label(api, cid, "not_constructive")
    label(api, "x", "discard")
    label(api, "s", "skip")

    body = api.get("/api/labeling/stats").json()
    assert body["counts"] == {"constructive": 3, "not_constructive": 4, "discarded": 1, "skipped": 1}
    assert body["labeled_total"] == 7
    assert body["labeled_today"] == 7
    assert body["remaining"] == 3  # two never seen and the skipped one
    assert body["by_depth"] == {"basic": 1, "specific": 0, "advanced": 1, "untagged": 1}
    assert body["by_aspect"]["audio"] == 2
    assert body["by_aspect"]["pacing"] == 1
    assert body["by_aspect"]["delivery"] == 0
    by_category = {c["category_id"]: c for c in body["by_category"]}
    assert (by_category["22"]["constructive"], by_category["22"]["not_constructive"]) == (3, 3)
    assert (by_category["10"]["constructive"], by_category["10"]["not_constructive"]) == (0, 1)

    prevalence = body["prevalence"]
    low, high = wilson_interval(3, 7)
    assert (prevalence["queue_mode"], prevalence["n"], prevalence["constructive"]) == ("random", 7, 3)
    assert prevalence["share"] == pytest.approx(3 / 7)
    assert (prevalence["low"], prevalence["high"]) == (pytest.approx(low), pytest.approx(high))
    assert "random" in prevalence["note"]


def test_the_prevalence_ignores_labels_from_other_queue_modes(api, mongo_db, db_session):
    seed(mongo_db, comment("a"), comment("b"))
    label(api, "a", "constructive")
    db_session.add(CommentLabel(comment_id="z", status="constructive", text="t", queue_mode="uncertainty"))
    db_session.flush()
    body = api.get("/api/labeling/stats").json()
    assert body["labeled_total"] == 2
    assert body["prevalence"]["n"] == 1


def test_labeled_today_ignores_older_labels(api, mongo_db, db_session):
    seed(mongo_db, comment("a"), comment("b"))
    label(api, "a", "not_constructive")
    label(api, "b", "not_constructive")
    rows(db_session)["a"].labeled_at = utcnow() - timedelta(days=2)
    db_session.flush()
    assert api.get("/api/labeling/stats").json()["labeled_today"] == 1


# ── independence from clients ───────────────────────────────────────────────


def test_deleting_a_client_leaves_the_labels_alone(api, mongo_db, db_session):
    seed(mongo_db, comment("a"))
    label(api, "a", "constructive", depth="basic")
    client = api.post("/api/clients", json={"name": "Acme"}).json()
    assert api.delete(f"/api/clients/{client['id']}").status_code == 200
    assert db_session.scalar(select(func.count()).select_from(CommentLabel)) == 1
    assert rows(db_session)["a"].text == "text of a"


def test_comment_label_has_no_link_to_a_client():
    assert not [c for c in CommentLabel.__table__.columns if "client" in c.name]
    assert not CommentLabel.__table__.foreign_keys
