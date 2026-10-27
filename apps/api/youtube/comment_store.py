"""The comment corpus, kept in MongoDB for at most 30 days like the rest of the public YouTube data.

Two collections, sharing the connection and the retention rule of `youtube.store`: `youtube_comment` (one document per
kept comment) and `youtube_crawl_video` (one per crawled video, with its stratum). Both have a TTL index on
`expires_at`. The corpus is research data, not tied to any client.

Comments carry an extra field, `dedupe_key`: a fingerprint of the normalised text, indexed, so that a copy-pasted
comment is recognised across runs without scanning every document.
"""
from collections.abc import Iterable
from datetime import datetime
from functools import lru_cache

from pymongo import ASCENDING, DESCENDING, ReplaceOne
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from config import settings
from youtube.store import RETENTION, StoreError, StoreNotConfigured, _connect, utcnow

COMMENT_COLLECTION = "youtube_comment"
VIDEO_COLLECTION = "youtube_crawl_video"


@lru_cache
def _prepare(url: str, database: str) -> tuple[Collection, Collection]:
    db = _connect(url)[database]
    comments, videos = db[COMMENT_COLLECTION], db[VIDEO_COLLECTION]
    for collection in (comments, videos):
        collection.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expires_at")  # 30-day rule
    comments.create_index([("video_id", ASCENDING)], name="by_video")
    comments.create_index([("dedupe_key", ASCENDING)], name="by_dedupe_key")
    return comments, videos


def collections() -> tuple[Collection, Collection]:
    if not settings.mongo_url:
        raise StoreNotConfigured("MongoDB is not configured (set MONGO_URL in .env). It stores the comment corpus.")
    try:
        return _prepare(settings.mongo_url, settings.mongo_db)
    except PyMongoError as exc:
        raise StoreError(f"Could not reach MongoDB ({type(exc).__name__}).") from None


def _live() -> dict:
    # The TTL monitor runs about once a minute, so reads ignore a document past its expiry themselves.
    return {"expires_at": {"$gt": utcnow()}}


def save_video(video, fetched_at: datetime) -> None:
    """Store (or renew) the crawled-video document for an `enrich.VideoRecord`."""
    document = {
        "_id": video.video_id, "video_id": video.video_id, "channel_id": video.channel_id, "title": video.title,
        "category_id": video.category_id, "published_at": video.published_at, "view_count": video.view_count,
        "comment_count": video.comment_count, "subscriber_count": video.subscriber_count,
        "default_language": video.default_language, "stratum": video.stratum, "source": video.source,
        "fetched_at": fetched_at, "expires_at": fetched_at + RETENTION,
    }
    try:
        collections()[1].replace_one({"_id": video.video_id}, document, upsert=True)
    except PyMongoError as exc:
        raise StoreError(f"Could not write to MongoDB ({type(exc).__name__}).") from None


def save_comments(documents: list[dict]) -> int:
    """Upsert comments by YouTube comment ID, so crawling a video twice never doubles it. Returns how many were sent."""
    if not documents:
        return 0
    try:
        collections()[0].bulk_write([ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in documents], ordered=False)
    except PyMongoError as exc:
        raise StoreError(f"Could not write to MongoDB ({type(exc).__name__}).") from None
    return len(documents)


def known_video_ids(ids: Iterable[str]) -> set[str]:
    """Which of these videos are already in the corpus (and so are not fetched again)."""
    try:
        found = collections()[1].find({"_id": {"$in": list(ids)}, **_live()}, {"_id": 1})
        return {d["_id"] for d in found}
    except PyMongoError as exc:
        raise StoreError(f"Could not read from MongoDB ({type(exc).__name__}).") from None


def known_dedupe_keys() -> set[str]:
    """The fingerprints of every comment in the corpus. A few dozen bytes each: 100,000 comments is a few megabytes."""
    try:
        return {d["dedupe_key"] for d in collections()[0].find(_live(), {"dedupe_key": 1}) if "dedupe_key" in d}
    except PyMongoError as exc:
        raise StoreError(f"Could not read from MongoDB ({type(exc).__name__}).") from None


def coverage_rows() -> list[dict]:
    """Videos and comments per cell, for `strata.coverage`."""
    axes = ("category_id", "view_band", "subscriber_band", "age_band")
    group = {axis: f"$stratum.{axis}" for axis in axes}
    try:
        videos, comments = [
            {tuple(row["_id"][axis] for axis in axes): row["n"] for row in collection.aggregate([
                {"$match": _live()}, {"$group": {"_id": group, "n": {"$sum": 1}}}])}
            for collection in (collections()[1], collections()[0])
        ]
    except PyMongoError as exc:
        raise StoreError(f"Could not read from MongoDB ({type(exc).__name__}).") from None
    return [
        {**dict(zip(axes, cell, strict=True)), "videos": videos.get(cell, 0), "comments": comments.get(cell, 0)}
        for cell in videos.keys() | comments.keys()
    ]


def load_comments(video_id: str | None = None, limit: int = 0) -> list[dict]:
    """Unexpired comments, newest first, optionally of one video."""
    query = {**_live(), **({"video_id": video_id} if video_id else {})}
    try:
        return list(collections()[0].find(query).sort("published_at", DESCENDING).limit(limit))
    except PyMongoError as exc:
        raise StoreError(f"Could not read from MongoDB ({type(exc).__name__}).") from None


def count_comments() -> int:
    try:
        return collections()[0].count_documents(_live())
    except PyMongoError as exc:
        raise StoreError(f"Could not read from MongoDB ({type(exc).__name__}).") from None


def purge_expired() -> int:
    """Delete expired documents of both collections right now. Returns the number deleted."""
    try:
        return sum(c.delete_many({"expires_at": {"$lte": utcnow()}}).deleted_count for c in collections())
    except PyMongoError as exc:
        raise StoreError(f"Could not delete from MongoDB ({type(exc).__name__}).") from None
