"""Strata for the comment corpus: which kind of video a comment came from, and how well each kind is covered.

A classifier trained on whatever the API returns first would learn the comments of big channels. To avoid that, every
video is placed in a cell, category x view band x subscriber band x age band, and the crawler goes where cells are
empty. The edges below are explicit, lower bound inclusive: exactly 1,000 views is in "1k-10k".
"""
import random
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

VIEW_EDGES = (1_000, 10_000, 100_000, 1_000_000)
VIEW_BANDS = ("<1k", "1k-10k", "10k-100k", "100k-1M", "1M+")
SUBSCRIBER_EDGES = VIEW_EDGES
SUBSCRIBER_BANDS = (*VIEW_BANDS, "hidden")  # "hidden": the channel does not show its subscriber count

# Age at crawl time, in days: 30 days is a month, 183 half a year, 365 a year, 1095 three years.
AGE_EDGES_DAYS = (30, 183, 365, 1095)
AGE_BANDS = ("<1mo", "1mo-6mo", "6mo-1y", "1y-3y", "3y+")
OLDEST_VIDEO_DAYS = 3650  # search windows in "3y+" are drawn from the last ten years

# The categories videos can be uploaded to (videoCategories.list for a region is the authority; these are the
# stable ids). Movies, Shows and Trailers are not assignable by uploaders, so they are not crawled.
CATEGORIES = {
    "1": "Film & Animation", "2": "Autos & Vehicles", "10": "Music", "15": "Pets & Animals", "17": "Sports",
    "19": "Travel & Events", "20": "Gaming", "22": "People & Blogs", "23": "Comedy", "24": "Entertainment",
    "25": "News & Politics", "26": "Howto & Style", "27": "Education", "28": "Science & Technology",
    "29": "Nonprofits & Activism",
}

HIGH_VIEW_BANDS = ("100k-1M", "1M+")
HIGH_AUDIENCE_SHARE = 0.4  # two of the five view bands: below this share, older bands are searched by view count

Cell = tuple[str, str, str, str]  # category_id, view_band, subscriber_band, age_band
AXES = ("category_id", "view_band", "subscriber_band", "age_band")


def _band(value: int, edges: tuple[int, ...], labels: tuple[str, ...]) -> str:
    return labels[bisect_right(edges, value)]


def view_band(views: int) -> str:
    return _band(views, VIEW_EDGES, VIEW_BANDS)


def subscriber_band(subscribers: int | None) -> str:
    """None means the channel hides its count. YouTube rounds the figure down to three significant figures, which
    never moves it across an edge here."""
    return "hidden" if subscribers is None else _band(subscribers, SUBSCRIBER_EDGES, VIEW_BANDS)


def age_band(published_at: datetime, now: datetime) -> str:
    return AGE_BANDS[bisect_right(AGE_EDGES_DAYS, (now - published_at).days)]


def age_range_days(band: str) -> tuple[int, int]:
    """The (youngest, oldest) age in days that falls in a band."""
    i = AGE_BANDS.index(band)
    low = 0 if i == 0 else AGE_EDGES_DAYS[i - 1]
    high = AGE_EDGES_DAYS[i] if i < len(AGE_EDGES_DAYS) else OLDEST_VIDEO_DAYS
    return low, high


def stratum(category_id: str, views: int, subscribers: int | None, published_at: datetime, now: datetime) -> dict:
    return {
        "category_id": category_id, "view_band": view_band(views),
        "subscriber_band": subscriber_band(subscribers), "age_band": age_band(published_at, now),
    }


def random_window(band: str, now: datetime, rng: random.Random, hours: int) -> tuple[datetime, datetime]:
    """A window of `hours` hours placed at random so that it lies entirely inside the age band."""
    low, high = age_range_days(band)
    span = timedelta(days=high - low) - timedelta(hours=hours)
    start = now - timedelta(days=high) + timedelta(seconds=rng.uniform(0, span.total_seconds()))
    return start, start + timedelta(hours=hours)


@dataclass
class Count:
    videos: int = 0
    comments: int = 0

    def add(self, videos: int, comments: int) -> None:
        self.videos += videos
        self.comments += comments


class Coverage:
    """How many crawled videos and kept comments each cell, and each single axis value, holds."""

    def __init__(self) -> None:
        self.cells: dict[Cell, Count] = defaultdict(Count)
        self.axes: dict[str, dict[str, Count]] = {axis: defaultdict(Count) for axis in AXES}

    def add(self, cell: Cell, videos: int = 0, comments: int = 0) -> None:
        self.cells[cell].add(videos, comments)
        for axis, value in zip(AXES, cell, strict=True):
            self.axes[axis][value].add(videos, comments)

    def pair(self, category_id: str, band: str) -> Count:
        """Everything in one category x age band, whatever the view and subscriber bands."""
        total = Count()
        for (category, _, _, age), count in self.cells.items():
            if category == category_id and age == band:
                total.add(count.videos, count.comments)
        return total

    def high_audience_share(self, band: str) -> float:
        """Share of the age band's videos in the 100k+ view bands; 0 when the band is empty."""
        total = sum(c.videos for (_, _, _, age), c in self.cells.items() if age == band)
        high = sum(c.videos for (_, view, _, age), c in self.cells.items() if age == band and view in HIGH_VIEW_BANDS)
        return high / total if total else 0.0


def coverage(rows: Iterable[Mapping]) -> Coverage:
    """Build the counts from rows like {"category_id", "view_band", "subscriber_band", "age_band", "videos",
    "comments"} (what the store's aggregation returns)."""
    result = Coverage()
    for row in rows:
        result.add(tuple(row[axis] for axis in AXES), row.get("videos", 0), row.get("comments", 0))
    return result


def next_targets(
    cov: Coverage, rng: random.Random, n: int = 1, exclude: Iterable[tuple[str, str]] = ()
) -> list[tuple[str, str]]:
    """The (category, age band) pairs to search next: the ones with the fewest kept comments, then the fewest videos.
    Ties are broken by the seeded RNG, so a run is repeatable and equally empty pairs are visited in random order."""
    excluded = set(exclude)
    ranked = []
    for category in CATEGORIES:
        for band in AGE_BANDS:
            if (category, band) not in excluded:
                count = cov.pair(category, band)
                ranked.append((count.comments, count.videos, rng.random(), category, band))
    ranked.sort()
    return [(category, band) for *_, category, band in ranked[:n]]
