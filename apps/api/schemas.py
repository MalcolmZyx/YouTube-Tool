"""Request and response models.

These double as the API contract: FastAPI validates incoming data against them, filters
outgoing data through them and publishes them in the generated OpenAPI docs (/docs).
"""
import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class EnrichOut(BaseModel):
    requested: int  # videos that needed public data
    stored: int
    unavailable: int  # private, deleted or unknown on YouTube


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


# ── clients and uploads ─────────────────────────────────────────────────────


class ClientIn(BaseModel):
    name: str = Field(max_length=200)
    youtube_channel_id: str | None = Field(default=None, pattern=r"^UC[A-Za-z0-9_-]{22}$")
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ClientOut(BaseModel):
    id: uuid.UUID
    name: str
    youtube_channel_id: str | None
    notes: str | None
    created_at: datetime
    upload_count: int
    video_count: int


class ClientDeletedOut(BaseModel):
    """What was erased with the client, so the confirmation can say exactly what is gone."""

    deleted: dict[str, int]


class PeriodIn(BaseModel):
    """The date range an upload covers, as confirmed by the person who knows (the operator)."""

    kind: Literal["lifetime", "range"]
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def _dates_match_kind(self) -> "PeriodIn":
        if self.kind == "range":
            if self.start is None or self.end is None:
                raise ValueError("a range needs both start and end")
            if self.start > self.end:
                raise ValueError("start must not be after end")
        elif self.start is not None or self.end is not None:
            raise ValueError("lifetime takes no dates")
        return self


class UploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_type: str
    original_filename: str
    row_count: int
    period_kind: str
    period_start: date | None
    period_end: date | None
    period_source: str | None
    exported_on: date | None
    imported_at: datetime


class ImportOut(BaseModel):
    upload_id: int
    duplicate: bool
    videos: int
    metric_values: int
    total_values: int
    period_kind: str
    period_start: date | None
    period_end: date | None
    period_source: str | None
    new_unreviewed_metrics: list[str]
    warnings: list[str]
