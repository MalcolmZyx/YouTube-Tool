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


class QuotaOut(BaseModel):
    limit: int
    used_today: int
    remaining: int
    used_last_7_days: int
    resets_at: datetime  # when the quota day rolls over (midnight Pacific time)
    estimate: bool = True  # our own count: it cannot see calls made with the same key elsewhere


class PublicDataAlertOut(BaseModel):
    client_id: uuid.UUID
    client_name: str
    level: str  # "expired" (already hidden from the analyses) or "expiring" (within 7 days)
    stored: int
    expired: int
    expiring_soon: int
    next_expiry: datetime | None


class PublicDataDeletedOut(BaseModel):
    deleted_videos: int


class PortalStatusOut(BaseModel):
    configured: bool
    published: dict[str, datetime]  # snapshot kind -> when it was last published


class PortalRequestOut(BaseModel):
    id: int
    client_id: uuid.UUID
    client_name: str | None  # None if the client no longer exists here
    type: str
    note: str
    status: str
    created_at: datetime
    updated_at: datetime


class RequestStatusIn(BaseModel):
    status: Literal["requested", "approved", "declined", "done"]


class PermissionIn(BaseModel):
    status: Literal["requested", "granted", "denied", "expired"]
    quota: int | None = Field(default=None, ge=0, le=1_000_000)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class PermissionOut(BaseModel):
    feature: str
    status: str
    quota: int | None
    expires_at: datetime | None


class PreferenceOut(BaseModel):
    focus: dict[str, Any]
    updated_at: datetime | None


class InboxItemOut(BaseModel):
    id: int
    client_id: uuid.UUID
    client_name: str | None
    original_filename: str
    size_bytes: int
    created_at: datetime


class PullOutcomeOut(BaseModel):
    inbox_id: int
    client_name: str | None
    filename: str
    result: str  # imported | duplicate | rejected | skipped
    detail: str


class FindingOut(BaseModel):
    key: str
    title: str
    headline: str
    strength: str  # solid | suggestive | weak | not_enough_data | info
    details: dict[str, Any]
    caveats: list[str]


class AuditOut(BaseModel):
    upload_id: int
    filename: str
    period_kind: str
    as_of: date
    as_of_source: str
    videos: int
    findings: list[FindingOut]


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


# ── comment labeling ────────────────────────────────────────────────────────

# Queue modes the API accepts. Only 'random' exists; enriched and uncertainty modes get added here later.
QueueMode = Literal["random"]
LabelDepth = Literal["basic", "specific", "advanced"]
LabelAspect = Literal["audio", "video_quality", "pacing", "content_accuracy", "title_thumbnail", "delivery", "other"]


class CommentOut(BaseModel):
    """A comment to label. The text is plain; the page must show it as text, never as HTML."""

    comment_id: str
    text: str
    video_title: str | None
    like_count: int
    published_at: datetime | None
    stratum: dict[str, Any]


class QueueOut(BaseModel):
    mode: QueueMode
    items: list[CommentOut]


class LabelIn(BaseModel):
    comment_id: str = Field(min_length=1)
    decision: Literal["constructive", "not_constructive", "discard", "skip"]
    depth: LabelDepth | None = None
    aspects: list[LabelAspect] = Field(default_factory=list, max_length=len(LabelAspect.__args__))
    queue_mode: QueueMode = "random"  # the mode that served the comment

    @field_validator("aspects")
    @classmethod
    def _unique(cls, aspects: list[str]) -> list[str]:
        return list(dict.fromkeys(aspects))

    @model_validator(mode="after")
    def _tags_only_when_constructive(self):
        if self.decision != "constructive" and (self.depth or self.aspects):
            raise ValueError("depth and aspects can only be set on a constructive label")
        return self


class PrevalenceOut(BaseModel):
    queue_mode: QueueMode
    n: int
    constructive: int
    share: float | None
    low: float | None  # Wilson 95% interval
    high: float | None
    note: str


class CategoryCountOut(BaseModel):
    category_id: str | None
    constructive: int
    not_constructive: int


class LabelStatsOut(BaseModel):
    counts: dict[str, int]
    labeled_total: int  # constructive + not constructive
    labeled_today: int
    remaining: int  # in the pool and not yet decided (never seen, or skipped)
    prevalence: PrevalenceOut
    by_depth: dict[str, int]
    by_aspect: dict[str, int]
    by_category: list[CategoryCountOut]


class LabelResultOut(BaseModel):
    stats: LabelStatsOut
    next: CommentOut | None


class UndoOut(BaseModel):
    stats: LabelStatsOut
    undone: CommentOut | None  # the comment to show again, if its text is still available
