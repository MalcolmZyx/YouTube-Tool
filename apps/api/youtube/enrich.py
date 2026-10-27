"""Turn candidate video IDs into videos worth reading comments from, each placed in its stratum.

Two calls, both 1 unit per 50: `videos.list` (snippet, statistics, status) for every candidate, then `channels.list`
(statistics) only for the channels of the videos that survived.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from youtube import strata
from youtube.client import BATCH_SIZE, Api, batches

MIN_COMMENTS = 3


@dataclass(frozen=True)
class VideoRecord:
    video_id: str
    channel_id: str
    title: str
    category_id: str
    published_at: datetime
    view_count: int
    comment_count: int
    subscriber_count: int | None  # None when the channel hides it
    default_language: str | None
    stratum: dict
    source: str


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _subscribers(channel: dict | None) -> int | None:
    statistics = (channel or {}).get("statistics", {})
    if statistics.get("hiddenSubscriberCount") or "subscriberCount" not in statistics:
        return None
    return int(statistics["subscriberCount"])


def _channel_statistics(api: Api, channel_ids: list[str]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for batch in batches(sorted(set(channel_ids)), BATCH_SIZE):
        body = api.call("channels", {"part": "statistics", "id": ",".join(batch)})
        found.update({item["id"]: item for item in body.get("items", [])})
    return found


def enrich(
    api: Api, sources: dict[str, str], now: datetime, min_comments: int = MIN_COMMENTS
) -> tuple[list[VideoRecord], Counter]:
    """`sources` maps each candidate video ID to how it was found. Returns the videos to crawl, and a count of the
    others by reason: unavailable, made_for_kids, comments_disabled (no commentCount), few_comments."""
    dropped: Counter = Counter()
    kept: list[tuple[dict, str]] = []
    for batch in batches(sources):
        body = api.call("videos", {"part": "snippet,statistics,status", "id": ",".join(batch)})
        items = {item["id"]: item for item in body.get("items", [])}
        for video_id in batch:
            item = items.get(video_id)
            if item is None:
                dropped["unavailable"] += 1
            elif item.get("status", {}).get("madeForKids"):
                dropped["made_for_kids"] += 1
            elif "commentCount" not in item.get("statistics", {}):
                dropped["comments_disabled"] += 1
            elif int(item["statistics"]["commentCount"]) < min_comments:
                dropped["few_comments"] += 1
            else:
                kept.append((item, sources[video_id]))

    channels = _channel_statistics(api, [item["snippet"]["channelId"] for item, _ in kept]) if kept else {}
    records = []
    for item, source in kept:
        snippet, statistics = item["snippet"], item["statistics"]
        published_at = _parse_time(snippet["publishedAt"])
        views = int(statistics.get("viewCount", 0))
        subscribers = _subscribers(channels.get(snippet["channelId"]))
        category_id = snippet.get("categoryId", "")
        records.append(VideoRecord(
            video_id=item["id"], channel_id=snippet["channelId"], title=snippet.get("title", ""),
            category_id=category_id, published_at=published_at, view_count=views,
            comment_count=int(statistics["commentCount"]), subscriber_count=subscribers,
            default_language=snippet.get("defaultLanguage"),
            stratum=strata.stratum(category_id, views, subscribers, published_at, now), source=source,
        ))
    return records, dropped
