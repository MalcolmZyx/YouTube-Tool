"""Request and response models.

These double as the API contract: FastAPI validates incoming data against them, filters
outgoing data through them and publishes them in the generated OpenAPI docs (/docs).
"""
from typing import Any, Literal

from pydantic import BaseModel, Field

# ── settings / health ───────────────────────────────────────────────────────


class SettingsOut(BaseModel):
    has_api_key: bool
    key_preview: str


class SaveSettingsIn(BaseModel):
    api_key: str


class SaveSettingsOut(BaseModel):
    ok: bool
    message: str


class HealthOut(BaseModel):
    status: str
    cache_loaded: bool


# ── dashboard ───────────────────────────────────────────────────────────────


class DatasetOut(BaseModel):
    """An uploaded export after cleaning. Column names come from the file, so rows are free-form."""

    rows: list[dict[str, Any]]
    total_row: dict[str, Any] | None
    columns: list[str]
    text_columns: list[str]
    numeric_columns: list[str]
    percent_columns: list[str]
    shares: dict[str, dict[int, float]]
    video_id_col: str


# ── analysis ────────────────────────────────────────────────────────────────


class CalendarPoint(BaseModel):
    date: str
    value: float


class DayOfWeekStat(BaseModel):
    dow: int | None = None
    day: str
    total: float
    avg: float
    count: int


class HeatmapOut(BaseModel):
    calendar: list[CalendarPoint]
    day_of_week: list[DayOfWeekStat]
    metric: str | None = None
    available_metrics: list[str]


class TagScore(BaseModel):
    tag: str
    score: float


class WeightedTagsOut(BaseModel):
    tags: list[TagScore]


class TopVsBottomOut(BaseModel):
    top: list[TagScore]
    bottom: list[TagScore]


class DurationBucket(BaseModel):
    bucket: str
    count: int
    mean: float
    median: float
    total: float


class DurationOut(BaseModel):
    buckets: list[DurationBucket]
    metric: str | None = None


class DescriptionItem(BaseModel):
    video_id: str
    title: str
    description: str
    url: str
    thumbnail_url: str
    char_count: int
    line_count: int
    has_links: bool
    has_hashtags: bool
    has_timestamps: bool


class DescriptionsOut(BaseModel):
    videos: list[DescriptionItem]
    total: int


# ── researcher ──────────────────────────────────────────────────────────────


class SearchIn(BaseModel):
    query: str
    # YouTube returns at most 50 results per search request.
    max_results: int = Field(default=20, ge=1, le=50)
    order: Literal["relevance", "viewCount", "date", "rating"] = "relevance"
    published_after: str | None = None
    published_before: str | None = None
    video_duration: Literal["any", "short", "medium", "long"] = "any"
    top_n: int = Field(default=20, ge=1, le=100)


class ResearchVideo(BaseModel):
    video_id: str
    title: str
    url: str
    channel: str
    published_at: str
    views: int
    likes: int
    comment_count: int
    tags: list[str]
    thumbnail: str
    description: str


class SearchOut(BaseModel):
    videos: list[ResearchVideo]
    tags: list[TagScore]
    total: int


class IdeasOut(BaseModel):
    ideas: list[str]
    topic: str
