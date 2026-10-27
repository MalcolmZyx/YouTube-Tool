"""Public YouTube API data, kept in MongoDB for at most 30 days.

Why MongoDB and not Postgres: this is raw JSON returned by an API (its shape is YouTube's, not ours), and it carries
a legal lifetime. YouTube's rule for non-authorized data (Developer Policies III.E.4.d) is "delete or refresh within 30
days". A MongoDB TTL index on `expires_at` makes the database delete each document itself, so the rule holds even if
nobody ever clicks the alerts. The creator's own exported figures stay in Postgres.

One document per client and video. `raw` is exactly the snippet YouTube returned; the fields the app uses (description,
tags, thumbnail) are derived from it when read, so a different use of the same data needs no new fetch.
"""
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from pymongo import ASCENDING, MongoClient, ReplaceOne
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import PyMongoError
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from db.models import Video
from youtube.client import VideoInfo, describe, fetch_videos

RETENTION = timedelta(days=30)
REFRESH_AFTER = timedelta(days=7)  # renewed well before expiry, so a missed run does not lose data
COLLECTION = "youtube_video"

Fetcher = Callable[[Iterable[str], str], dict[str, VideoInfo]]


class StoreError(Exception):
    """The public-data store could not be reached. The message is safe to show (it never contains the URL)."""


class StoreNotConfigured(StoreError):
    pass


@lru_cache
def _connect(url: str) -> MongoClient:
    # Connection failures should surface in seconds, not after the driver's default 30.
    return MongoClient(url, serverSelectionTimeoutMS=3000, tz_aware=True)


@lru_cache
def _prepare(url: str, database: str) -> Collection:
    collection = _connect(url)[database][COLLECTION]
    collection.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expires_at")  # the 30-day rule
    collection.create_index([("client_id", ASCENDING)], name="by_client")
    return collection


def collection() -> Collection:
    if not settings.mongo_url:
        raise StoreNotConfigured("MongoDB is not configured (set MONGO_URL in .env). It stores the YouTube data.")
    try:
        return _prepare(settings.mongo_url, settings.mongo_db)
    except PyMongoError as exc:
        raise StoreError(f"Could not reach MongoDB ({type(exc).__name__}).") from None


def database() -> Database:
    """The MongoDB database itself, for code that reads collections other than `youtube_video`."""
    if not settings.mongo_url:
        raise StoreNotConfigured("MongoDB is not configured (set MONGO_URL in .env). It stores the YouTube data.")
    try:
        return _connect(settings.mongo_url)[settings.mongo_db]
    except PyMongoError as exc:
        raise StoreError(f"Could not reach MongoDB ({type(exc).__name__}).") from None


def is_configured() -> bool:
    return bool(settings.mongo_url)


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class RefreshResult:
    requested: int = 0
    stored: int = 0
    unavailable: int = 0  # private, deleted or unknown videos: nothing public to store


def videos_due(session: Session, client_id: uuid.UUID, force: bool = False) -> list[str]:
    """YouTube IDs of the client's videos with no public data yet, or data older than REFRESH_AFTER."""
    ids = list(session.scalars(select(Video.youtube_video_id).where(Video.client_id == client_id).order_by(Video.id)))
    if force:
        return ids
    try:
        fresh_since = utcnow() - REFRESH_AFTER
        fresh = {
            d["youtube_video_id"] for d in collection().find(
                {"client_id": str(client_id), "fetched_at": {"$gte": fresh_since}}, {"youtube_video_id": 1})
        }
    except PyMongoError as exc:
        raise StoreError(f"Could not read from MongoDB ({type(exc).__name__}).") from None
    return [i for i in ids if i not in fresh]


def refresh_client(
    session: Session, client_id: uuid.UUID, api_key: str, fetch: Fetcher = fetch_videos, force: bool = False
) -> RefreshResult:
    """Fetch public details for the client's videos that need them and store them for 30 days."""
    due = videos_due(session, client_id, force)
    result = RefreshResult(requested=len(due))
    if not due:
        return result

    found = fetch(due, api_key)
    now = utcnow()
    documents = []
    for youtube_id in due:
        info = found.get(youtube_id)
        documents.append(ReplaceOne(
            {"_id": f"{client_id}:{youtube_id}"},
            {
                "client_id": str(client_id), "youtube_video_id": youtube_id,
                "availability": "public" if info else "unavailable",
                "raw": info.snippet if info else None,
                "fetched_at": now, "expires_at": now + RETENTION,
            },
            upsert=True,
        ))
        if info:
            result.stored += 1
        else:
            result.unavailable += 1
    try:
        collection().bulk_write(documents, ordered=False)
    except PyMongoError as exc:
        raise StoreError(f"Could not write to MongoDB ({type(exc).__name__}).") from None
    return result


def purge_expired() -> int:
    """Delete documents past their expiry right now. MongoDB's TTL monitor does the same within about a minute; this
    is for an immediate cleanup and for the command line. Returns the number deleted."""
    try:
        return collection().delete_many({"expires_at": {"$lte": utcnow()}}).deleted_count
    except PyMongoError as exc:
        raise StoreError(f"Could not delete from MongoDB ({type(exc).__name__}).") from None


def delete_client_data(client_id: uuid.UUID) -> int:
    """Erase everything stored for a client. Used by the manual delete button and when a client is deleted."""
    try:
        return collection().delete_many({"client_id": str(client_id)}).deleted_count
    except PyMongoError as exc:
        raise StoreError(f"Could not delete from MongoDB ({type(exc).__name__}).") from None


def load_public_data(client_id: uuid.UUID) -> dict[str, dict]:
    """Unexpired public data by YouTube ID: description, thumbnail, category and tags.

    A document past its expiry is ignored even if MongoDB's TTL monitor has not removed it yet.
    """
    try:
        documents = collection().find({
            "client_id": str(client_id), "availability": "public", "expires_at": {"$gt": utcnow()},
        })
        return {d["youtube_video_id"]: describe(d["raw"] or {}) for d in documents}
    except PyMongoError as exc:
        raise StoreError(f"Could not read from MongoDB ({type(exc).__name__}).") from None
