"""Fetch public video details from the YouTube Data API, 50 videos per request.

Cost: `videos.list` is 1 quota unit per request whatever the number of IDs (up to 50), so 1,000 videos cost about
20 units of the default 10,000 a day. Only public data is requested, and only `snippet`.
"""
import logging
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
BATCH_SIZE = 50  # the API's maximum number of IDs per videos.list call
_THUMBNAIL_PREFERENCE = ("maxres", "standard", "high", "medium", "default")


class YouTubeError(RuntimeError):
    """The API refused or failed. The message never contains the key."""


class QuotaExceeded(YouTubeError):
    """The daily quota is used up; retrying today will not help."""


@dataclass(frozen=True)
class VideoInfo:
    video_id: str
    description: str
    tags: list[str] = field(default_factory=list)
    category_id: str | None = None
    thumbnail_url: str | None = None
    published_at: datetime | None = None


def batches(ids: Iterable[str], size: int = BATCH_SIZE) -> Iterator[list[str]]:
    batch: list[str] = []
    for video_id in ids:
        batch.append(video_id)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def _thumbnail(thumbnails: dict) -> str | None:
    for size in _THUMBNAIL_PREFERENCE:
        if url := thumbnails.get(size, {}).get("url"):
            return url
    return None


def _parse(item: dict) -> VideoInfo:
    snippet = item.get("snippet", {})
    published = snippet.get("publishedAt")
    return VideoInfo(
        video_id=item["id"],
        description=snippet.get("description", ""),
        tags=list(snippet.get("tags", [])),
        category_id=snippet.get("categoryId"),
        thumbnail_url=_thumbnail(snippet.get("thumbnails", {})),
        published_at=datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None,
    )


def _error_reason(response: requests.Response) -> str:
    try:
        error = response.json()["error"]
        return error["errors"][0]["reason"] if error.get("errors") else error.get("message", "unknown")
    except (ValueError, KeyError, IndexError, TypeError):
        return "unknown"


def fetch_videos(
    ids: Iterable[str], api_key: str, get: Callable[..., requests.Response] | None = None
) -> dict[str, VideoInfo]:
    """Public details for the given IDs. A private, deleted or unknown video is simply absent from the result."""
    get = get or requests.get
    found: dict[str, VideoInfo] = {}
    for batch in batches(ids):
        try:
            response = get(ENDPOINT, params={"part": "snippet", "id": ",".join(batch), "key": api_key}, timeout=15)
        except requests.RequestException as exc:
            # The exception text can contain the request URL, and the URL contains the key.
            raise YouTubeError(f"Could not reach the YouTube API ({type(exc).__name__})") from None
        if response.status_code != 200:
            reason = _error_reason(response)
            logger.warning("YouTube API returned %s (%s)", response.status_code, reason)
            if reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"):
                raise QuotaExceeded("The YouTube API daily quota is used up. Try again tomorrow.")
            if reason in ("keyInvalid", "API_KEY_INVALID", "badRequest"):
                raise YouTubeError("The YouTube API rejected the key. Check it in Settings.")
            raise YouTubeError(f"The YouTube API returned an error ({response.status_code}, {reason}).")
        for item in response.json().get("items", []):
            info = _parse(item)
            found[info.video_id] = info
    return found
