"""Fetch public video details from the YouTube Data API, 50 videos per request.

Cost: `videos.list` is 1 quota unit per request whatever the number of IDs (up to 50), so 1,000 videos cost about
20 units of the default 10,000 a day. Only public data is requested, and only `snippet`.
"""
import logging
from collections import Counter
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


class SearchBudgetExhausted(YouTubeError):
    """The separate daily bucket of `search.list` calls is used up. Every other method still works."""


class ApiError(YouTubeError):
    """Any other refusal by the API. `status` and `reason` let the caller tell a skippable case (comments
    disabled, a category without a chart) from a real failure."""

    def __init__(self, status: int, reason: str):
        super().__init__(f"The YouTube API returned an error ({status}, {reason}).")
        self.status, self.reason = status, reason


@dataclass(frozen=True)
class VideoInfo:
    video_id: str
    description: str
    tags: list[str] = field(default_factory=list)
    category_id: str | None = None
    thumbnail_url: str | None = None
    published_at: datetime | None = None
    snippet: dict = field(default_factory=dict, repr=False)  # exactly what the API returned, for the raw store


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


def describe(snippet: dict) -> dict:
    """The fields the app uses, derived from a raw API snippet. Tags are lower-cased and de-duplicated."""
    tags = sorted({t.strip().lower() for t in snippet.get("tags", []) if t and t.strip()})
    return {
        "description": snippet.get("description", ""),
        "tags": tags,
        "category_id": snippet.get("categoryId"),
        "thumbnail_url": _thumbnail(snippet.get("thumbnails", {})) or "",
    }


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
        snippet=snippet,
    )


def _error_reason(response: requests.Response) -> str:
    try:
        error = response.json()["error"]
        return error["errors"][0]["reason"] if error.get("errors") else error.get("message", "unknown")
    except (ValueError, KeyError, IndexError, TypeError):
        return "unknown"


def request_json(url: str, params: dict, api_key: str, get: Callable[..., requests.Response] | None = None) -> dict:
    """GET one API method and return its JSON body. Errors are translated; no message contains the key."""
    get = get or requests.get
    try:
        response = get(url, params={**params, "key": api_key}, timeout=15)
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
        raise ApiError(response.status_code, reason)
    return response.json()


def fetch_videos(
    ids: Iterable[str], api_key: str, get: Callable[..., requests.Response] | None = None
) -> dict[str, VideoInfo]:
    """Public details for the given IDs. A private, deleted or unknown video is simply absent from the result."""
    found: dict[str, VideoInfo] = {}
    for batch in batches(ids):
        body = request_json(ENDPOINT, {"part": "snippet", "id": ",".join(batch)}, api_key, get)
        for item in body.get("items", []):
            info = _parse(item)
            found[info.video_id] = info
    return found


API_ROOT = "https://www.googleapis.com/youtube/v3/"
# Every method the crawler calls costs 1 unit per request. `search.list` is charged to its own bucket (since
# 2026-06-01), limited to 100 calls a day by default; the others share the main pool.
SEARCH_DAILY_CALLS = 100


class Api:
    """One API key, one HTTP function, and a count of the calls made per method (the crawler's quota accounting)."""

    def __init__(self, api_key: str, get: Callable[..., requests.Response] | None = None,
                 search_limit: int = SEARCH_DAILY_CALLS):
        self._key, self._get, self.search_limit = api_key, get, search_limit
        self.calls: Counter[str] = Counter()

    def call(self, method: str, params: dict) -> dict:
        if method == "search" and self.calls[method] >= self.search_limit:
            raise SearchBudgetExhausted("The daily limit of search calls is used up.")
        self.calls[method] += 1
        try:
            return request_json(API_ROOT + method, params, self._key, self._get)
        except QuotaExceeded:
            if method == "search":  # the search bucket ran out; the main pool may be fine
                raise SearchBudgetExhausted("The daily limit of search calls is used up.") from None
            raise

    @property
    def main_units(self) -> int:
        """Units charged to the main daily pool: every call except `search`."""
        return sum(n for method, n in self.calls.items() if method != "search")
