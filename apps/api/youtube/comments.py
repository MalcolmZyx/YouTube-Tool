"""Read the top-level comments of one video and keep a small, filtered, random sample of them.

`commentThreads.list` (1 unit a page, 100 threads a page). Only the text and counts are kept: never an author name,
profile image or channel URL. The author's channel ID is kept only as a salted hash, and only if a salt is configured,
so the same person can be recognised across comments without being identifiable.

The text is requested as plain text and read from `textDisplay`: `textOriginal` is visible only to the comment's author.
"""
import hashlib
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from youtube import text
from youtube.client import Api, ApiError
from youtube.comment_store import RETENTION
from youtube.enrich import VideoRecord

MAX_PAGES = 2
PER_VIDEO_CAP = 25
DISABLED = "comments_disabled"
SKIPPED_REASONS = ("commentsDisabled", "videoNotFound")


@dataclass
class VideoComments:
    kept: list[dict] = field(default_factory=list)
    dropped: Counter = field(default_factory=Counter)  # insubstantial, not_english, duplicate, over_cap
    skipped: str | None = None  # why no comments could be read, e.g. "comments_disabled"


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def author_hash(channel_id: str | None, salt: str) -> str | None:
    if not salt or not channel_id:
        return None
    return hashlib.sha256((salt + channel_id).encode("utf-8")).hexdigest()


def _threads(api: Api, video_id: str, max_pages: int) -> list[dict]:
    items: list[dict] = []
    page_token = None
    for _ in range(max_pages):
        params = {
            "part": "snippet", "videoId": video_id, "maxResults": 100, "order": "time", "textFormat": "plainText",
        }
        if page_token:
            params["pageToken"] = page_token
        body = api.call("commentThreads", params)
        items.extend(body.get("items", []))
        page_token = body.get("nextPageToken")
        if not page_token:
            break
    return items


def _document(thread: dict, video: VideoRecord, cleaned: str, probability: float, salt: str,
              sampling: str, now: datetime) -> dict:
    top = thread["snippet"]["topLevelComment"]
    snippet = top["snippet"]
    return {
        "_id": top["id"], "comment_id": top["id"], "video_id": video.video_id, "is_reply": False, "parent_id": None,
        "text": cleaned, "like_count": int(snippet.get("likeCount", 0)),
        "reply_count": int(thread["snippet"].get("totalReplyCount", 0)),
        "published_at": _parse_time(snippet["publishedAt"]), "updated_at": _parse_time(snippet["updatedAt"]),
        "author_hash": author_hash(snippet.get("authorChannelId", {}).get("value"), salt),
        "lang": "en", "lang_prob": round(probability, 4),
        "stratum": {**video.stratum, "sampling": sampling}, "dedupe_key": text.dedupe_key(cleaned),
        "fetched_at": now, "expires_at": now + RETENTION,
    }


def fetch_comments(
    api: Api, video: VideoRecord, rng: random.Random, seen: set[str], now: datetime, salt: str = "",
    max_pages: int = MAX_PAGES, per_video_cap: int = PER_VIDEO_CAP,
) -> VideoComments:
    """Read up to `max_pages` pages of the newest threads, drop what fails a filter, and keep a seeded random sample
    of at most `per_video_cap` of the rest, so that no single video dominates the corpus.

    `seen` holds the dedupe keys of every comment already in the corpus; the sampled comments' keys are added to it.
    """
    result = VideoComments()
    try:
        threads = _threads(api, video.video_id, max_pages)
    except ApiError as exc:
        if exc.reason not in SKIPPED_REASONS:
            raise
        result.skipped = DISABLED if exc.reason == "commentsDisabled" else "video_not_found"
        return result

    sampling = f"time_pages_{max_pages}"
    passed: list[dict] = []
    local: set[str] = set()
    for thread in threads:
        raw = thread["snippet"]["topLevelComment"]["snippet"].get("textDisplay", "")
        cleaned = text.clean_comment(raw)
        if not text.is_substantial(cleaned):
            result.dropped["insubstantial"] += 1
            continue
        key = text.dedupe_key(cleaned)
        if key in seen or key in local:
            result.dropped["duplicate"] += 1
            continue
        probability = text.english_probability(cleaned)
        if not text.is_english(probability):
            result.dropped["not_english"] += 1
            continue
        local.add(key)
        passed.append(_document(thread, video, cleaned, probability, salt, sampling, now))

    chosen = rng.sample(passed, min(per_video_cap, len(passed)))
    if len(passed) > len(chosen):
        result.dropped["over_cap"] = len(passed) - len(chosen)
    for document in chosen:
        seen.add(document["dedupe_key"])
    result.kept = chosen
    return result
