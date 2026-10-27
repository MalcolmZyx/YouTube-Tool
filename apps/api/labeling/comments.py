"""The crawled comments in MongoDB, and the order they are served in.

The crawler writes one document per comment to `youtube_comment` and one per video to `youtube_crawl_video`. Both are
deleted by a 30-day TTL, so a comment can vanish while it is on screen; every read here treats a document past its
`expires_at` as already gone, even if MongoDB's TTL monitor has not removed it yet.
"""
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from typing import Any

from pymongo.errors import PyMongoError

from youtube import store

COMMENTS = "youtube_comment"
VIDEOS = "youtube_crawl_video"

# $sample is drawn from a pool this many times larger than the queue, so that spreading videos apart (see _spread)
# has real choices to make.
OVERSAMPLE = 4


@contextmanager
def _reading() -> Iterator[None]:
    try:
        yield
    except PyMongoError as exc:
        raise store.StoreError(f"Could not read from MongoDB ({type(exc).__name__}).") from None


def _live() -> dict[str, Any]:
    """Top-level comments that have not expired. Replies are left out: they depend on the comment they answer."""
    return {"is_reply": False, "expires_at": {"$gt": store.utcnow()}}


def find(comment_id: str) -> dict | None:
    """The comment with its video title, or None if it is gone."""
    with _reading():
        doc = store.database()[COMMENTS].find_one({"_id": comment_id, "expires_at": {"$gt": store.utcnow()}})
        return None if doc is None else _item(doc, _titles([doc["video_id"]]))


def _titles(video_ids: Collection[str]) -> dict[str, str]:
    videos = store.database()[VIDEOS].find({"_id": {"$in": list(video_ids)}}, {"title": 1})
    return {v["_id"]: v.get("title") for v in videos}


def _item(doc: dict, titles: dict[str, str]) -> dict:
    return {
        "comment_id": doc["_id"], "text": doc["text"], "video_id": doc["video_id"],
        "video_title": titles.get(doc["video_id"]), "like_count": doc.get("like_count", 0),
        "published_at": doc.get("published_at"), "stratum": doc.get("stratum") or {},
    }


def _sample(match: dict, size: int) -> list[dict]:
    seen: set[str] = set()
    docs = []
    for doc in store.database()[COMMENTS].aggregate([{"$match": match}, {"$sample": {"size": size * OVERSAMPLE}}]):
        if doc["_id"] not in seen:  # $sample may repeat a document
            seen.add(doc["_id"])
            docs.append(doc)
    return docs


def _spread(docs: list[dict], count: int) -> list[dict]:
    """Pick `count` comments in an order where neighbours come from different videos whenever the sample allows.

    The sample is already random; this only avoids reading ten comments of one video in a row, which would make the
    labeler judge them against each other. Each step takes the first remaining comment from a video other than the
    previous one, and falls back to the first remaining one when only that video is left.
    """
    remaining = list(docs)
    ordered: list[dict] = []
    while remaining and len(ordered) < count:
        last = ordered[-1]["video_id"] if ordered else None
        pick = next((d for d in remaining if d["video_id"] != last), remaining[0])
        remaining.remove(pick)
        ordered.append(pick)
    return ordered


def next_comments(
    labeled: Collection[str], skipped: Collection[str], count: int, avoid: str | None = None
) -> list[dict]:
    """Up to `count` comments to label, never-seen ones first and skipped ones only after those run out.

    `labeled` is every comment id that already has a decision, `skipped` the subset that was skipped. `avoid` keeps
    the comment just decided from coming straight back when only skipped ones remain.
    """
    seen = set(labeled) | ({avoid} if avoid else set())
    with _reading():
        fresh = _spread(_sample({**_live(), "_id": {"$nin": list(seen)}}, count), count)
        docs = fresh
        if len(fresh) < count:
            retry = [i for i in skipped if i != avoid]
            back = _sample({**_live(), "_id": {"$in": retry}}, count - len(fresh))
            docs = fresh + _spread(back, count - len(fresh))
        titles = _titles({d["video_id"] for d in docs})
        return [_item(d, titles) for d in docs]


def remaining(finished: Collection[str]) -> int:
    """Comments in the pool without a final decision (never seen, or skipped). `finished` are the decided ids."""
    with _reading():
        return store.database()[COMMENTS].count_documents({**_live(), "_id": {"$nin": list(finished)}})
