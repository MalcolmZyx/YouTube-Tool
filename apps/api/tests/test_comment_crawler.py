"""The comment crawler: discovery, enrichment, comment sampling, the store, quota accounting and the commands.

Every HTTP call goes to `FakeYouTube`; the store tests use the throw-away MongoDB database of the `mongo` fixture.
"""
import random
from collections import Counter
from datetime import timedelta

import pytest
from comment_fakes import KEY, NOW, FakeYouTube, english, error, thread
from sqlalchemy import text as sql

from youtube import comment_store, comments, crawler, discovery, strata
from youtube.__main__ import main
from youtube.client import Api, ApiError, QuotaExceeded, SearchBudgetExhausted, YouTubeError
from youtube.enrich import enrich


@pytest.fixture
def fake():
    return FakeYouTube()


@pytest.fixture
def api(fake):
    return Api(KEY, fake)


# ── discovery ───────────────────────────────────────────────────────────────


def test_search_by_date_asks_for_a_window_inside_the_age_band_that_widens_with_age(api, fake):
    fake.search = [("v1", "UC1"), ("v2", "UC2")]

    found = discovery.search_window(api, "20", "1y-3y", NOW, random.Random(1))

    (method, params), = fake.calls
    assert method == "search"
    assert (params["type"], params["order"], params["videoCategoryId"], params["relevanceLanguage"]) == (
        "video", "date", "20", "en")
    assert params["maxResults"] == 50 and params["part"] == "snippet"
    after, before = (discovery.datetime.strptime(params[k], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=NOW.tzinfo)
                     for k in ("publishedAfter", "publishedBefore"))
    assert before - after == timedelta(hours=discovery.DATE_WINDOW_HOURS["1y-3y"])
    assert strata.age_band(after, NOW) == strata.age_band(before, NOW) == "1y-3y"
    assert params["q"] in discovery.QUERY_WORDS
    assert [(c.video_id, c.channel_id, c.source) for c in found] == [
        ("v1", "UC1", "search_window"), ("v2", "UC2", "search_window")]

    hours = [discovery.DATE_WINDOW_HOURS[band] for band in strata.AGE_BANDS]
    assert hours == sorted(hours) and hours[0] == 2


def test_the_common_word_of_a_date_search_comes_from_the_seed(fake):
    def words(seed):
        rng, api, chosen = random.Random(seed), Api(KEY, fake), []
        for _ in range(12):
            discovery.search_window(api, "20", "<1mo", NOW, rng)
            chosen.append(fake.calls[-1][1]["q"])
        return chosen

    assert words(1) == words(1) and set(words(1)) == set(discovery.QUERY_WORDS)


def test_search_by_view_count_uses_a_wider_window(api, fake):
    fake.search = [("v1", "UC1")]

    found = discovery.search_window(api, "10", "3y+", NOW, random.Random(1), by_view_count=True)

    params = fake.calls[0][1]
    assert params["order"] == "viewCount" and "q" not in params
    start, end = params["publishedAfter"], params["publishedBefore"]
    assert (discovery.datetime.fromisoformat(end) - discovery.datetime.fromisoformat(start)) == timedelta(hours=72)
    assert found[0].source == "search_viewcount"


def test_a_chart_is_read_per_category_and_an_unsupported_one_is_skipped(api, fake, caplog):
    fake.add_video("v1", "UC1", category="20")
    fake.charts = {"20": ["v1"]}

    assert [c.video_id for c in discovery.most_popular(api, "20")] == ["v1"]
    params = fake.calls[0][1]
    assert (params["chart"], params["videoCategoryId"], params["regionCode"]) == ("mostPopular", "20", "US")

    fake.errors["videos"] = error(400, "videoChartNotFound")
    assert discovery.most_popular(api, "29") == []
    assert "videoChartNotFound" in caplog.text


def test_a_refused_search_is_skipped_but_quota_errors_are_not_swallowed(fake):
    fake.errors["search"] = error(400, "invalidSearchFilter")
    assert discovery.search_window(Api(KEY, fake), "29", "<1mo", NOW, random.Random(0)) == []

    fake.errors["search"] = error(403, "quotaExceeded")
    with pytest.raises(SearchBudgetExhausted):  # the search bucket, not the main pool
        discovery.search_window(Api(KEY, fake), "20", "<1mo", NOW, random.Random(0))

    fake.errors["videos"] = error(403, "quotaExceeded")
    with pytest.raises(QuotaExceeded):
        discovery.most_popular(Api(KEY, fake), "20")


def test_the_search_bucket_stops_at_its_limit_and_the_main_pool_does_not_count_it(fake):
    api = Api(KEY, fake, search_limit=2)
    api.call("search", {})
    api.call("search", {})
    with pytest.raises(SearchBudgetExhausted):
        api.call("search", {})
    api.call("videos", {"id": "x"})

    assert (api.calls["search"], api.main_units) == (2, 1)


def test_uploads_come_from_the_playlist_named_by_the_channel(api, fake):
    fake.uploads = {"UCabc": ["v1", "v2"]}

    found = discovery.channel_uploads(api, "UCabc")

    assert [(c.video_id, c.source) for c in found] == [("v1", "uploads"), ("v2", "uploads")]
    assert fake.calls[0][1]["part"] == "contentDetails"
    assert fake.calls[1][1]["playlistId"] == "UUabc"  # as returned by relatedPlaylists.uploads
    assert discovery.channel_uploads(api, "UCmissing") == []


def test_errors_never_contain_the_key(fake):
    fake.errors["videos"] = error(500, "backendError")
    with pytest.raises(ApiError) as caught:
        Api(KEY, fake).call("videos", {"id": "x"})
    assert KEY not in str(caught.value) and (caught.value.status, caught.value.reason) == (500, "backendError")

    def unreachable(url, params, timeout):
        import requests
        raise requests.ConnectionError(f"{url}?key={params['key']}")

    with pytest.raises(YouTubeError) as caught:
        Api(KEY, unreachable).call("videos", {})
    assert KEY not in str(caught.value)


# ── enrichment ──────────────────────────────────────────────────────────────


def test_enrich_drops_kids_disabled_and_quiet_videos_and_places_the_rest_in_strata(api, fake):
    fake.add_video("good", "UC1", views=2_500, comments=40, age_days=100, subscribers=12_000)
    fake.add_video("kids", "UC2", kids=True)
    fake.add_video("off", "UC3", comments=None)
    fake.add_video("quiet", "UC4", comments=2)
    fake.add_video("hidden", "UC5")
    fake.channels["UC5"] = {"hiddenSubscriberCount": True}
    sources = dict.fromkeys(["good", "kids", "off", "quiet", "hidden", "gone"], "search_window")

    records, dropped = enrich(api, sources, NOW)

    assert {r.video_id for r in records} == {"good", "hidden"}
    assert dict(dropped) == {"made_for_kids": 1, "comments_disabled": 1, "few_comments": 1, "unavailable": 1}
    good = next(r for r in records if r.video_id == "good")
    assert (good.view_count, good.comment_count, good.subscriber_count) == (2500, 40, 12000)
    assert good.default_language == "en"
    assert good.stratum == {"category_id": "20", "view_band": "1k-10k", "subscriber_band": "10k-100k",
                            "age_band": "1mo-6mo"}
    assert next(r for r in records if r.video_id == "hidden").subscriber_count is None
    assert next(r for r in records if r.video_id == "hidden").stratum["subscriber_band"] == "hidden"


def test_the_minimum_comment_count_can_be_changed(api, fake):
    fake.add_video("v", "UC1", comments=5)
    assert enrich(api, {"v": "uploads"}, NOW, min_comments=6)[0] == []
    assert len(enrich(api, {"v": "uploads"}, NOW, min_comments=5)[0]) == 1


def test_enrich_batches_fifty_videos_and_asks_only_for_surviving_channels(api, fake):
    for i in range(60):
        fake.add_video(f"v{i:02}", f"UC{i % 3}", comments=40 if i < 55 else 0)

    records, dropped = enrich(api, dict.fromkeys(fake.videos, "most_popular"), NOW)

    assert len(records) == 55 and dropped["few_comments"] == 5
    assert (fake.count("videos"), fake.count("channels")) == (2, 1)  # 60 ids -> 50 + 10; 3 channels -> 1 call
    assert fake.calls[-1][1]["part"] == "statistics"


def test_enrich_makes_no_channel_call_when_nothing_survives(api, fake):
    fake.add_video("kids", "UC1", kids=True)
    assert enrich(api, {"kids": "uploads"}, NOW)[0] == []
    assert fake.count("channels") == 0


# ── comments ────────────────────────────────────────────────────────────────


def _video(api, fake, video_id="v1", **kwargs):
    fake.add_video(video_id, "UC1", **kwargs)
    return enrich(api, {video_id: "search_window"}, NOW)[0][0]


def test_comments_are_requested_as_plain_text_newest_first(api, fake):
    video = _video(api, fake, comments_per_page=(3,))

    comments.fetch_comments(api, video, random.Random(0), set(), NOW)

    params = fake.calls[-1][1]
    assert (params["part"], params["videoId"], params["maxResults"], params["order"], params["textFormat"]) == (
        "snippet", "v1", 100, "time", "plainText")


def test_the_document_has_the_contract_fields_and_no_author_identity(api, fake):
    fake.add_video("v1", "UC1", comments_per_page=(1,))
    fake.threads["v1"] = [[thread("c1", "Thanks @Maria for the tip, see https://x.co/a", likes=7, replies=2)]]
    video = enrich(api, {"v1": "uploads"}, NOW)[0][0]

    (doc,) = comments.fetch_comments(api, video, random.Random(0), set(), NOW).kept

    assert set(doc) == {
        "_id", "comment_id", "video_id", "is_reply", "parent_id", "text", "like_count", "reply_count", "published_at",
        "updated_at", "author_hash", "lang", "lang_prob", "stratum", "dedupe_key", "fetched_at", "expires_at"}
    assert (doc["_id"], doc["comment_id"], doc["video_id"], doc["is_reply"], doc["parent_id"]) == (
        "c1", "c1", "v1", False, None)
    assert doc["text"] == "Thanks @user for the tip, see <url>"
    assert (doc["like_count"], doc["reply_count"], doc["lang"]) == (7, 2, "en")
    assert doc["published_at"].tzinfo is not None and doc["expires_at"] - doc["fetched_at"] == timedelta(days=30)
    assert doc["stratum"]["sampling"] == "time_pages_2" and doc["stratum"]["category_id"] == "20"
    assert doc["author_hash"] is None  # no salt configured
    flat = repr(doc)
    for forbidden in ("Some Person", "http://img", "http://c/x", "UCauthor1"):
        assert forbidden not in flat


def test_the_author_is_hashed_only_when_a_salt_is_set(api, fake):
    video = _video(api, fake, comments_per_page=(1,))

    salted = comments.fetch_comments(api, video, random.Random(0), set(), NOW, salt="pepper").kept[0]
    assert salted["author_hash"] == comments.author_hash("UCauthor1", "pepper") and len(salted["author_hash"]) == 64
    assert "UCauthor1" not in salted["author_hash"]
    assert comments.author_hash("UCauthor1", "other") != salted["author_hash"]
    assert comments.author_hash(None, "pepper") is None


def test_comments_failing_a_filter_are_dropped_and_counted(api, fake):
    fake.add_video("v1", "UC1")
    texts = [
        english("gardening", 1), "\U0001F602\U0001F602", "3:20", "lol", "@user hi",
        "Este video me ayudo mucho a entender como funciona todo esto", english("gardening", 1),
        english("gardening", 1).upper() + " \U0001F44D!!",
    ]
    fake.threads["v1"] = [[thread(f"c{i}", t) for i, t in enumerate(texts)]]
    video = enrich(api, {"v1": "uploads"}, NOW)[0][0]

    result = comments.fetch_comments(api, video, random.Random(0), set(), NOW)

    assert [d["comment_id"] for d in result.kept] == ["c0"]
    assert dict(result.dropped) == {"insubstantial": 4, "not_english": 1, "duplicate": 2}


def test_spam_already_in_the_corpus_is_dropped(api, fake):
    video = _video(api, fake, comments_per_page=(2,))
    seen: set[str] = set()
    first = comments.fetch_comments(api, video, random.Random(0), seen, NOW)
    assert len(first.kept) == 2 and len(seen) == 2

    again = comments.fetch_comments(api, video, random.Random(0), seen, NOW)

    assert again.kept == [] and again.dropped["duplicate"] == 2


def test_at_most_the_cap_is_kept_as_a_seeded_random_sample(api, fake):
    video = _video(api, fake, comments_per_page=(100, 60))

    def kept(seed, cap=25):
        return [d["comment_id"] for d in comments.fetch_comments(
            api, video, random.Random(seed), set(), NOW, per_video_cap=cap).kept]

    assert len(kept(1)) == 25 and len(set(kept(1))) == 25
    assert kept(1) == kept(1) and kept(1) != kept(2)  # repeatable per seed, random between seeds
    assert set(kept(1)) != {f"v1-0-{i}" for i in range(25)}  # not just the first 25
    assert any(c.startswith("v1-1-") for c in kept(1) + kept(2) + kept(3))  # the second page is in the pool
    result = comments.fetch_comments(api, video, random.Random(1), set(), NOW, per_video_cap=10)
    assert len(result.kept) == 10 and result.dropped["over_cap"] == 160 - 10


def test_only_max_pages_pages_are_read(api, fake):
    video = _video(api, fake, comments_per_page=(10, 10, 10))
    before = fake.count("commentThreads")

    comments.fetch_comments(api, video, random.Random(0), set(), NOW, max_pages=2)
    assert fake.count("commentThreads") - before == 2

    before = fake.count("commentThreads")
    result = comments.fetch_comments(api, video, random.Random(0), set(), NOW, max_pages=1, per_video_cap=100)
    assert fake.count("commentThreads") - before == 1
    assert result.kept[0]["stratum"]["sampling"] == "time_pages_1"


def test_a_video_with_comments_disabled_is_recorded_as_skipped(api, fake):
    video = _video(api, fake)
    fake.errors["commentThreads:v1"] = error(403, "commentsDisabled")

    result = comments.fetch_comments(api, video, random.Random(0), set(), NOW)

    assert result.skipped == "comments_disabled" and result.kept == []


def test_other_comment_errors_are_not_hidden(api, fake):
    video = _video(api, fake)
    fake.errors["commentThreads"] = error(500, "backendError")
    with pytest.raises(ApiError):
        comments.fetch_comments(api, video, random.Random(0), set(), NOW)


# ── the store ───────────────────────────────────────────────────────────────


def _stored_video(api, fake, video_id="v1", **kwargs):
    fake.add_video(video_id, f"UC-{video_id}", **kwargs)
    return enrich(api, {video_id: "search_window"}, NOW)[0][0]


def test_round_trip_and_the_thirty_day_indexes(mongo, api, fake):
    video = _stored_video(api, fake, comments_per_page=(3,))
    docs = comments.fetch_comments(api, video, random.Random(0), set(), NOW).kept

    comment_store.save_video(video, NOW)
    assert comment_store.save_comments(docs) == 3
    comment_store.save_comments(docs)  # crawling again does not double anything

    assert comment_store.count_comments() == 3
    loaded = {d["_id"]: d for d in comment_store.load_comments("v1")}
    assert set(loaded) == {"v1-0-0", "v1-0-1", "v1-0-2"}
    assert {d["_id"]: d["text"] for d in docs} == {i: d["text"] for i, d in loaded.items()}
    stored_video = mongo.database["youtube_crawl_video"].find_one({"_id": "v1"})
    assert set(stored_video) == {
        "_id", "video_id", "channel_id", "title", "category_id", "published_at", "view_count", "comment_count",
        "subscriber_count", "default_language", "stratum", "source", "fetched_at", "expires_at"}
    assert stored_video["source"] == "search_window" and "sampling" not in stored_video["stratum"]
    for name in (comment_store.COMMENT_COLLECTION, comment_store.VIDEO_COLLECTION):
        index = mongo.database[name].index_information()["ttl_expires_at"]
        assert index["key"] == [("expires_at", 1)] and index["expireAfterSeconds"] == 0
    assert comment_store.known_video_ids(["v1", "nope"]) == {"v1"}
    assert comment_store.known_dedupe_keys() == {d["dedupe_key"] for d in docs}


def test_expired_documents_are_ignored_and_purged(mongo, api, fake):
    video = _stored_video(api, fake, comments_per_page=(2,))
    docs = comments.fetch_comments(api, video, random.Random(0), set(), NOW).kept
    comment_store.save_video(video, NOW)
    comment_store.save_comments(docs)
    past = comment_store.utcnow() - timedelta(days=1)
    mongo.database[comment_store.COMMENT_COLLECTION].update_many({}, {"$set": {"expires_at": past}})
    mongo.database[comment_store.VIDEO_COLLECTION].update_many({}, {"$set": {"expires_at": past}})

    assert comment_store.count_comments() == 0 and comment_store.known_video_ids(["v1"]) == set()
    assert comment_store.coverage_rows() == [] and comment_store.known_dedupe_keys() == set()
    assert comment_store.purge_expired() == 3  # two comments and the video


def test_coverage_rows_count_videos_and_comments_per_cell(mongo, api, fake):
    seen: set[str] = set()
    for video_id, kwargs in (("a", {"views": 500}), ("b", {"views": 500}), ("c", {"views": 5_000})):
        video = _stored_video(api, fake, video_id, comments_per_page=(2,), **kwargs)
        comment_store.save_video(video, NOW)
        comment_store.save_comments(comments.fetch_comments(api, video, random.Random(0), seen, NOW).kept)

    rows = {row["view_band"]: row for row in comment_store.coverage_rows()}

    assert (rows["<1k"]["videos"], rows["<1k"]["comments"]) == (2, 4)
    assert (rows["1k-10k"]["videos"], rows["1k-10k"]["comments"]) == (1, 2)
    assert strata.coverage(comment_store.coverage_rows()).axes["category_id"]["20"].videos == 3


def test_an_unconfigured_store_says_so(monkeypatch):
    monkeypatch.setattr(comment_store.settings, "mongo_url", "")
    with pytest.raises(comment_store.StoreNotConfigured, match="MONGO_URL"):
        comment_store.count_comments()


# ── the crawl loop ──────────────────────────────────────────────────────────


def _world(fake, n=6):
    """n videos from n small channels; every search returns all of them."""
    for i in range(n):
        fake.add_video(f"vid{i}", f"UC{i}", views=300 + i, comments=30, age_days=3, subscribers=800,
                       comments_per_page=(30, 30))
    fake.search = [(f"vid{i}", f"UC{i}") for i in range(n)]


def test_a_crawl_keeps_the_requested_number_of_videos_with_capped_comments(mongo, api, fake):
    _world(fake)

    summary = crawler.crawl(api, 4, seed=1, now=NOW, per_video_cap=10)

    assert (summary.videos_kept, summary.comments_kept, summary.stop_reason) == (4, 40, "target_reached")
    assert comment_store.count_comments() == 40
    assert summary.dropped["over_cap"] == 4 * 50
    assert summary.units["videos"] == 1 and summary.units["commentThreads"] == 8 and summary.units["search"] == 1
    assert api.main_units == 1 + 1 + 8  # videos.list, channels.list, eight comment pages
    kept_videos = list(mongo.database[comment_store.VIDEO_COLLECTION].find())
    assert len(kept_videos) == 4 and {v["source"] for v in kept_videos} <= {"search_window", "search_viewcount"}


def test_a_crawl_never_keeps_more_than_it_is_told_to_and_is_repeatable(mongo, api, fake):
    _world(fake)
    crawler.crawl(api, 3, seed=5, now=NOW)
    first = sorted(d["_id"] for d in comment_store.load_comments())

    comment_store.collections()[0].delete_many({})
    comment_store.collections()[1].delete_many({})
    crawler.crawl(Api(KEY, fake), 3, seed=5, now=NOW)

    assert sorted(d["_id"] for d in comment_store.load_comments()) == first


def test_a_crawl_stops_cleanly_when_the_main_quota_runs_out_and_keeps_what_it_read(mongo, api, fake):
    _world(fake)
    fake.errors["commentThreads"] = error(403, "quotaExceeded")

    summary = crawler.crawl(api, 5, seed=1, now=NOW)

    assert summary.stop_reason == "quota_exceeded" and summary.videos_kept == 0
    assert summary.units["search"] == 1  # it did not retry in a loop


def test_videos_read_before_the_quota_ran_out_are_kept(mongo, api, fake):
    _world(fake)
    state = {"left": 3}
    original = fake.__call__

    def limited(url, params, timeout):
        if url.endswith("commentThreads"):
            state["left"] -= 1
            if state["left"] < 0:
                return error(403, "quotaExceeded")
        return original(url, params, timeout)

    summary = crawler.crawl(Api(KEY, limited), 5, seed=1, now=NOW, max_pages=1)

    assert summary.stop_reason == "quota_exceeded" and summary.videos_kept == 3
    assert comment_store.count_comments() == summary.comments_kept > 0


def test_comments_disabled_videos_are_recorded_and_the_crawl_goes_on(mongo, api, fake):
    _world(fake)
    fake.errors["commentThreads:vid0"] = error(403, "commentsDisabled")

    summary = crawler.crawl(api, 5, seed=1, now=NOW)

    assert summary.videos_kept == 5 and summary.dropped["comments_disabled"] == 1
    assert comment_store.known_video_ids(["vid0"]) == {"vid0"}  # recorded, so it is not fetched again
    assert comment_store.load_comments("vid0") == []


def test_when_the_search_bucket_is_used_up_the_crawl_continues_with_charts_and_uploads(mongo, fake):
    _world(fake, n=4)
    for i in range(4, 8):
        fake.add_video(f"vid{i}", f"UCpop{i}", comments_per_page=(10,))
    fake.charts = {category: [f"vid{i}" for i in range(4, 8)] for category in strata.CATEGORIES}
    fake.uploads = {"UC0": ["vid0"]}
    api = Api(KEY, fake, search_limit=1)

    summary = crawler.crawl(api, 8, seed=2, now=NOW)

    assert summary.videos_kept == 8 and api.calls["search"] == 1 and api.calls["videos"] > 2
    sources = {v["source"] for v in mongo.database[comment_store.VIDEO_COLLECTION].find()}
    assert "most_popular" in sources


def test_a_crawl_with_nothing_to_find_gives_up_instead_of_spinning(mongo, api, fake):
    summary = crawler.crawl(api, 5, seed=1, now=NOW)

    assert summary.videos_kept == 0 and summary.stop_reason == "no_new_videos"
    assert summary.rounds <= crawler.MAX_EMPTY_ROUNDS


def test_the_unit_budget_stops_the_run_before_it_overspends(mongo, api, fake):
    _world(fake)

    summary = crawler.crawl(api, 5, seed=1, now=NOW, unit_budget=10)

    assert summary.stop_reason == "unit_budget" and api.main_units == 0


def test_a_crawl_balances_towards_empty_cells(mongo, fake):
    """Pre-fill every pair except one: the next search must be for the empty one."""
    _world(fake)
    rows = [
        {"category_id": c, "view_band": "<1k", "subscriber_band": "<1k", "age_band": a, "videos": 1, "comments": 50}
        for c in strata.CATEGORIES for a in strata.AGE_BANDS if (c, a) != ("27", "6mo-1y")
    ]
    for i, row in enumerate(rows):
        mongo.database[comment_store.VIDEO_COLLECTION].insert_one(
            {"_id": f"old{i}", "stratum": row | {"sampling": "x"}, "expires_at": NOW + timedelta(days=400)})
    api = Api(KEY, fake)

    crawler.crawl(api, 1, seed=3, now=NOW)

    first_search = next(p for m, p in fake.calls if m in ("search", "videos") and p.get("videoCategoryId"))
    assert first_search["videoCategoryId"] == "27"


# ── steering by audience ────────────────────────────────────────────────────


def _corpus(mongo, per_view_band: dict[str, int]):
    """Crawled videos in the given view bands, spread evenly over five categories, subscriber and age bands."""
    i = 0
    for view, n in per_view_band.items():
        for _ in range(n):
            stratum = {"category_id": list(strata.CATEGORIES)[i % 5], "view_band": view, "sampling": "x",
                       "subscriber_band": strata.SUBSCRIBER_BANDS[i % 5], "age_band": strata.AGE_BANDS[i % 5]}
            mongo.database[comment_store.VIDEO_COLLECTION].insert_one(
                {"_id": f"old{i}", "stratum": stratum, "expires_at": NOW + timedelta(days=400)})
            i += 1


def _mixed_world(fake, small=6, big=6):
    for i in range(small):
        fake.add_video(f"small{i}", f"UCs{i}", views=400 + i, comments=30, age_days=(3, 60, 200)[i % 3],
                       subscribers=(800, 5_000, 50_000)[i % 3], comments_per_page=(30,))
    for i in range(big):
        fake.add_video(f"big{i}", f"UCb{i}", views=5_000_000 + i, comments=30, age_days=(3, 60, 200)[i % 3],
                       subscribers=(800, 5_000, 50_000)[i % 3], comments_per_page=(30,))
    fake.search = [(f"small{i}", f"UCs{i}") for i in range(small)] + [(f"big{i}", f"UCb{i}") for i in range(big)]


def test_videos_in_an_over_full_band_are_turned_away_before_any_comment_is_read(mongo, api, fake):
    _corpus(mongo, {"1M+": 28, "100k-1M": 2})
    _mixed_world(fake, small=3, big=3)

    summary = crawler.crawl(api, 3, seed=1, now=NOW)

    assert summary.videos_kept == 3 and summary.stop_reason == "target_reached"
    assert summary.dropped["over_quota_view_band"] == 3
    assert comment_store.known_video_ids(["small0", "small1", "small2"]) == {"small0", "small1", "small2"}
    assert comment_store.known_video_ids(["big0", "big1", "big2"]) == set()
    assert fake.count("commentThreads") == 3  # none was spent on the three that were turned away


def test_a_run_whose_candidates_are_all_over_quota_gives_up_without_reading_comments(mongo, api, fake):
    _corpus(mongo, {"1M+": 28, "100k-1M": 2})
    _mixed_world(fake, small=0, big=6)

    summary = crawler.crawl(api, 3, seed=1, now=NOW)

    assert summary.videos_kept == 0 and summary.stop_reason == "no_new_videos"
    assert summary.dropped["over_quota_view_band"] >= 6 and fake.count("commentThreads") == 0


def test_the_quota_decision_is_repeatable_for_a_seed(mongo, api, fake):
    def run(seed):
        comment_store.collections()[0].delete_many({})
        comment_store.collections()[1].delete_many({})
        _corpus(mongo, {"1M+": 28, "100k-1M": 2})
        summary = crawler.crawl(Api(KEY, fake), 4, seed=seed, now=NOW)
        kept = sorted(d["_id"] for d in comment_store.collections()[1].find({"_id": {"$not": {"$regex": "^old"}}}))
        return kept, dict(summary.dropped), summary.rounds

    _mixed_world(fake)
    assert run(5) == run(5)
    assert all(video.startswith("small") for video in run(5)[0])


def test_the_run_summary_names_the_axis_that_turned_videos_away(mongo, db_engine, clean_usage, fake, monkeypatch,
                                                                capsys):
    monkeypatch.setenv("YOUTUBE_API_KEY", KEY)
    _corpus(mongo, {"1M+": 28, "100k-1M": 2})
    _mixed_world(fake, small=3, big=3)

    assert main(["crawl", "--videos", "3", "--seed", "1"], engine=db_engine, get=fake) == 0

    assert "over_quota_view_band 3" in capsys.readouterr().out


@pytest.mark.parametrize("emptiest, order, has_word", [("100k-1M", "viewCount", False), ("<1k", "date", True)])
def test_the_search_follows_the_view_band_the_corpus_lacks(mongo, api, fake, emptiest, order, has_word):
    _corpus(mongo, {band: 6 for band in strata.VIEW_BANDS if band != emptiest})
    _mixed_world(fake)

    crawler.crawl(api, 1, seed=2, now=NOW)

    first = next(p for m, p in fake.calls if m == "search")
    assert first["order"] == order and ("q" in first) is has_word


def test_a_low_view_band_reads_a_small_channels_uploads_and_a_high_one_the_chart(api, fake):
    fake.add_video("v1", "UC1")
    fake.uploads = {"UCsmall": ["v1"]}
    fake.charts = {"20": ["v1"]}
    state = crawler._Crawl(api, 1, NOW, "US")
    state.search_open, state.small_channels = False, ["UCsmall"]

    assert [c.source for c in state.discover("20", "<1mo", "<1k")] == ["uploads"]
    assert [c.source for c in state.discover("20", "<1mo", "100k-1M")] == ["most_popular"]
    assert fake.count("search") == 0
    assert [c.source for c in state.discover("20", "<1mo", "1k-10k")] == ["most_popular"]  # the channel is used up


def test_a_new_run_reads_the_uploads_of_small_channels_already_in_the_corpus(mongo, fake):
    stratum = {"category_id": "20", "view_band": "<1k", "subscriber_band": "<1k", "age_band": "<1mo"}
    mongo.database[comment_store.VIDEO_COLLECTION].insert_one(
        {"_id": "old", "channel_id": "UCsmall", "stratum": stratum, "expires_at": NOW + timedelta(days=400)})
    fake.add_video("fresh", "UCsmall", views=300, comments=30, age_days=3, subscribers=800, comments_per_page=(30,))
    fake.uploads = {"UCsmall": ["fresh"]}
    api = Api(KEY, fake, search_limit=0)

    summary = crawler.crawl(api, 1, seed=1, now=NOW)

    assert summary.videos_kept == 1 and api.calls["search"] == 0
    assert [v["source"] for v in mongo.database[comment_store.VIDEO_COLLECTION].find({"_id": "fresh"})] == ["uploads"]


def _spy_on_targets(monkeypatch):
    chosen = []
    original = crawler._Crawl.discover

    def spy(self, category, band, view_band):
        chosen.append((category, band, view_band))
        return original(self, category, band, view_band)

    monkeypatch.setattr(crawler._Crawl, "discover", spy)
    return chosen


def test_a_pair_and_a_view_band_that_yield_nothing_are_dropped_after_a_few_rounds(mongo, api, fake, monkeypatch):
    chosen = _spy_on_targets(monkeypatch)

    summary = crawler.crawl(api, 5, seed=1, now=NOW)

    assert summary.stop_reason == "no_new_videos" and len(chosen) == crawler.MAX_EMPTY_ROUNDS
    assert max(Counter((c, b) for c, b, _ in chosen).values()) <= crawler.MAX_MISSES
    assert max(Counter(v for *_, v in chosen if v).values()) <= crawler.MAX_VIEW_MISSES
    assert chosen[-1][2] is None  # every view band had been given up on


def test_a_view_band_that_cannot_be_filled_is_given_up_and_the_run_ends_balanced(mongo, api, fake, monkeypatch):
    chosen = _spy_on_targets(monkeypatch)
    for i in range(30):
        fake.add_video(f"big{i}", f"UCb{i}", views=5_000_000 + i, comments=30, age_days=(3, 60, 200, 500, 2000)[i % 5],
                       category=list(strata.CATEGORIES)[i % 5], comments_per_page=(30,),
                       subscribers=(800, 5_000, 50_000, 500_000, 5_000_000)[i % 5])
    fake.search = [(f"big{i}", f"UCb{i}") for i in range(30)]

    summary = crawler.crawl(api, 100, seed=3, now=NOW)

    assert summary.videos_kept == strata.MIN_VIDEOS_FOR_QUOTA and summary.stop_reason == "no_new_videos"
    assert summary.dropped["over_quota_view_band"] > 0
    counts = Counter(v for *_, v in chosen)
    assert all(counts[band] <= crawler.MAX_VIEW_MISSES for band in strata.VIEW_BANDS[:4])


# ── the commands ────────────────────────────────────────────────────────────


@pytest.fixture
def clean_usage(db_engine):
    yield
    with db_engine.begin() as connection:
        connection.execute(sql("DELETE FROM api_usage"))


def test_crawl_command_prints_a_summary_and_records_main_pool_units(mongo, db_engine, clean_usage, fake, monkeypatch,
                                                                    capsys):
    monkeypatch.setenv("YOUTUBE_API_KEY", KEY)
    _world(fake)

    code = main(["crawl", "--videos", "3", "--seed", "1", "--per-video-cap", "10"], engine=db_engine, get=fake)

    out = capsys.readouterr().out
    assert code == 0 and "Kept 3 videos and 30 comments." in out and "target reached" in out
    assert "over_cap" in out and "commentThreads 6" in out and "search 1" in out and KEY not in out
    with db_engine.connect() as connection:
        spent = connection.execute(sql("SELECT coalesce(sum(units), 0) FROM api_usage")).scalar()
    assert spent == 1 + 1 + 6  # the search call is not in the main pool


def test_crawl_command_reports_quota_and_marks_it_used_up(mongo, db_engine, clean_usage, fake, monkeypatch, capsys):
    monkeypatch.setenv("YOUTUBE_API_KEY", KEY)
    _world(fake)
    fake.errors["videos"] = error(403, "quotaExceeded")

    code = main(["crawl", "--videos", "3"], engine=db_engine, get=fake)

    assert code == 0 and "quota exceeded" in capsys.readouterr().out
    from config import settings
    with db_engine.connect() as connection:
        assert connection.execute(sql("SELECT sum(units) FROM api_usage")).scalar() >= settings.youtube_daily_quota


def test_crawl_command_needs_a_key_and_a_store(db_engine, monkeypatch, capsys):
    assert main(["crawl", "--videos", "1"], engine=db_engine) == 1
    assert "YOUTUBE_API_KEY is not set" in capsys.readouterr().out

    monkeypatch.setenv("YOUTUBE_API_KEY", KEY)
    monkeypatch.setattr(comment_store.settings, "mongo_url", "")
    assert main(["crawl", "--videos", "1"], engine=db_engine, get=FakeYouTube()) == 1
    assert "not configured" in capsys.readouterr().out


def test_coverage_command_prints_every_axis_and_the_emptiest_pairs(mongo, db_engine, fake, capsys):
    assert main(["coverage"]) == 0
    empty = capsys.readouterr().out
    for heading in ("category_id", "view_band", "subscriber_band", "age_band", "Emptiest"):
        assert heading in empty
    assert "Cells with data: 0 of 2250." in empty

    _world(fake)
    crawler.crawl(Api(KEY, fake), 2, seed=1, now=NOW, per_video_cap=5)
    assert main(["coverage"]) == 0
    out = capsys.readouterr().out
    assert "Gaming" in out and "<1k" in out and "Cells with data: 1 of 2250." in out
    assert "100%" in out  # both videos are in one cell, so that cell holds every comment


def test_purge_removes_expired_comments_too(mongo, db_engine, capsys):
    comment_store.save_comments([{"_id": "old", "expires_at": comment_store.utcnow() - timedelta(days=1)}])

    assert main(["purge"], engine=db_engine) == 0
    assert "Purged 1 expired documents." in capsys.readouterr().out
