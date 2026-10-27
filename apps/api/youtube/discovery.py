"""Find candidate videos. Four ways, each answering a different gap in the corpus.

* `search_window`, order=date: all uploads in a short random window inside an age band. A window of a couple of
  hours holds mostly small channels, because there are far more of them: this is how low-audience videos are found.
* `search_window`, order=viewCount: the most viewed videos of a wider window. This reaches the high-audience end of
  the older age bands, which date order almost never returns.
* `most_popular`: the current chart of a category (`videos.list`, chart=mostPopular).
* `channel_uploads`: the latest uploads of a channel, read from its uploads playlist.

Costs: `search.list` is 1 unit of its own bucket of 100 calls a day (since 2026-06-01); the rest are 1 unit of the main
pool. Parameter names and limits are from developers.google.com/youtube/v3/docs. A category that does not support a
filter answers with an error; each function logs a refusal of the request and returns nothing, so one bad
category never ends a run. Quota, key and network errors are not swallowed.
"""
import logging
import random
from dataclasses import dataclass
from datetime import datetime

from youtube import strata
from youtube.client import Api, ApiError

logger = logging.getLogger(__name__)

SEARCH_MAX_RESULTS = 50  # search.list: 0-50 per page (and at most 500 per query; one page is used)
DATE_WINDOW_HOURS = 2
VIEWCOUNT_WINDOW_HOURS = 72  # a wider window, so that its most viewed videos are well viewed
UPLOADS_PER_CHANNEL = 10

SEARCH_WINDOW = "search_window"
SEARCH_VIEWCOUNT = "search_viewcount"
MOST_POPULAR = "most_popular"
UPLOADS = "uploads"


@dataclass(frozen=True)
class Candidate:
    video_id: str
    channel_id: str | None
    source: str


def _rfc3339(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _skipping(what: str, exc: ApiError) -> list[Candidate]:
    logger.warning("Skipping %s: %s", what, exc.reason)
    return []


def search_window(
    api: Api, category_id: str, age_band: str, now: datetime, rng: random.Random, by_view_count: bool = False
) -> list[Candidate]:
    """One search call: up to 50 videos of a category published inside a random window of the age band."""
    hours = VIEWCOUNT_WINDOW_HOURS if by_view_count else DATE_WINDOW_HOURS
    after, before = strata.random_window(age_band, now, rng, hours)
    source = SEARCH_VIEWCOUNT if by_view_count else SEARCH_WINDOW
    try:
        body = api.call("search", {
            "part": "snippet", "type": "video", "videoCategoryId": category_id, "relevanceLanguage": "en",
            "order": "viewCount" if by_view_count else "date", "maxResults": SEARCH_MAX_RESULTS,
            "publishedAfter": _rfc3339(after), "publishedBefore": _rfc3339(before),
        })
    except ApiError as exc:
        return _skipping(f"search in category {category_id}", exc)
    return [
        Candidate(item["id"]["videoId"], item.get("snippet", {}).get("channelId"), source)
        for item in body.get("items", []) if item.get("id", {}).get("videoId")
    ]


def most_popular(api: Api, category_id: str, region: str = "US") -> list[Candidate]:
    """The current chart of a category. Some categories have no chart: that is a 400 videoChartNotFound."""
    try:
        body = api.call("videos", {
            "part": "snippet", "chart": "mostPopular", "videoCategoryId": category_id, "regionCode": region,
            "maxResults": SEARCH_MAX_RESULTS,
        })
    except ApiError as exc:
        return _skipping(f"chart of category {category_id}", exc)
    return [
        Candidate(item["id"], item.get("snippet", {}).get("channelId"), MOST_POPULAR) for item in body.get("items", [])
    ]


def channel_uploads(api: Api, channel_id: str, count: int = UPLOADS_PER_CHANNEL) -> list[Candidate]:
    """The channel's latest uploads. The uploads playlist ID is read from the channel (contentDetails), not derived
    from the channel ID."""
    try:
        channels = api.call("channels", {"part": "contentDetails", "id": channel_id}).get("items", [])
        if not channels:
            return []
        playlist = channels[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        body = api.call("playlistItems", {"part": "snippet", "playlistId": playlist, "maxResults": count})
    except ApiError as exc:
        return _skipping(f"uploads of channel {channel_id}", exc)
    return [
        Candidate(item["snippet"]["resourceId"]["videoId"], channel_id, UPLOADS)
        for item in body.get("items", []) if item.get("snippet", {}).get("resourceId", {}).get("videoId")
    ]
