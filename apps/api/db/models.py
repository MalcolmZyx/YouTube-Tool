"""Database schema.

The reasoning behind every table is in docs/concepts/data-model.md. In short:

* Every table that belongs to a client carries `client_id`, and the child tables point at their
  parents with *composite* foreign keys that include `client_id`. The database itself then refuses
  to link one client's rows to another client's rows.
* Deleting a `client` row cascades to everything that belongs to it.
* Data fetched from the public YouTube API (retention limit: 30 days) lives in its own tables, so
  one cleanup job can expire it without touching the creator's exported figures.
* Metric values are stored in long format (one row per video, upload and metric) and described by
  a metric catalog, so a new Studio metric needs a catalog row, not a schema change.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

# Allowed values. They are stored as text with CHECK constraints rather than Postgres ENUM types,
# because adding a value to a CHECK is an ordinary migration, while altering an ENUM is awkward.
REPORT_TYPES = ("table_data",)
PERIOD_KINDS = ("unknown", "lifetime", "range")
PERIOD_SOURCES = ("filename", "inferred", "user")
AVAILABILITIES = ("public", "unavailable")
METRIC_UNITS = ("count", "percent", "hours", "minutes", "seconds", "usd", "ratio")
METRIC_AGGREGATIONS = ("sum", "ratio", "weighted_avg", "none")
REVIEW_STATUSES = ("reviewed", "unreviewed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Client(Base):
    """A creator you work with. Everything else hangs off this row."""

    __tablename__ = "client"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(Text)
    youtube_channel_id: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint(
            "youtube_channel_id IS NULL OR youtube_channel_id ~ '^UC[A-Za-z0-9_-]{22}$'",
            name="channel_id_format",
        ),
    )


class Upload(Base):
    """One file a client gave you. Metrics are attached to the upload they came from."""

    __tablename__ = "upload"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("client.id", ondelete="CASCADE"))
    report_type: Mapped[str] = mapped_column(Text)
    original_filename: Mapped[str] = mapped_column(Text)
    # Fingerprint of the file's bytes: importing the same file twice is detected, not duplicated.
    file_sha256: Mapped[str] = mapped_column(String(64))
    # What period do the numbers cover? A Studio export does not say, so it starts as 'unknown'
    # and is later inferred or confirmed by the user.
    period_kind: Mapped[str] = mapped_column(Text, server_default="unknown")
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    period_source: Mapped[str | None] = mapped_column(Text)
    exported_on: Mapped[date | None] = mapped_column(Date)
    row_count: Mapped[int] = mapped_column(Integer, server_default="0")
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("client_id", "file_sha256", name="client_file"),
        # Target for the composite foreign keys of child tables (see module docstring).
        UniqueConstraint("client_id", "id", name="client_id_id"),
        CheckConstraint(_in("report_type", REPORT_TYPES), name="report_type_known"),
        CheckConstraint(_in("period_kind", PERIOD_KINDS), name="period_kind_known"),
        CheckConstraint(
            "period_source IS NULL OR " + _in("period_source", PERIOD_SOURCES), name="period_source_known"
        ),
        CheckConstraint(
            "(period_kind = 'range' AND period_start IS NOT NULL AND period_end IS NOT NULL "
            "AND period_start <= period_end) "
            "OR (period_kind <> 'range' AND period_start IS NULL AND period_end IS NULL)",
            name="period_consistent",
        ),
        CheckConstraint("file_sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
        CheckConstraint("row_count >= 0", name="row_count_nonnegative"),
    )


class Video(Base):
    """A video that belongs to a client. Holds only what the creator's own export provides."""

    __tablename__ = "video"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("client.id", ondelete="CASCADE"))
    youtube_video_id: Mapped[str] = mapped_column(String(11))
    title: Mapped[str | None] = mapped_column(Text)
    published_on: Mapped[date | None] = mapped_column(Date)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("client_id", "youtube_video_id", name="client_youtube_video"),
        UniqueConstraint("client_id", "id", name="client_id_id"),
        CheckConstraint("youtube_video_id ~ '^[A-Za-z0-9_-]{11}$'", name="youtube_id_format"),
        CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="duration_nonnegative"),
    )


class VideoPublicMetadata(Base):
    """Fields fetched from the public YouTube API. Must be refreshed or deleted within 30 days."""

    __tablename__ = "video_public_metadata"

    video_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    description: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[str | None] = mapped_column(Text)
    # The export has no 'private' notion; the API simply returns nothing for a private or removed video.
    availability: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now() + interval '30 days'")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["client_id", "video_id"], ["video.client_id", "video.id"],
            ondelete="CASCADE",
            name="fk_video_public_metadata_video",
        ),
        CheckConstraint(_in("availability", AVAILABILITIES), name="availability_known"),
        CheckConstraint("expires_at > fetched_at", name="expiry_after_fetch"),
        # The cleanup job scans by expiry.
        Index("ix_video_public_metadata_expires_at", "expires_at"),
    )


class VideoTag(Base):
    """One tag on one video. API-sourced, so it expires together with the video's public metadata."""

    __tablename__ = "video_tag"

    video_id: Mapped[int] = mapped_column(BigInteger)
    tag: Mapped[str] = mapped_column(Text)
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid)

    __table_args__ = (
        PrimaryKeyConstraint("video_id", "tag", name="pk_video_tag"),
        ForeignKeyConstraint(
            ["client_id", "video_id"], ["video.client_id", "video.id"],
            ondelete="CASCADE",
            name="fk_video_tag_video",
        ),
        # Tags are stored normalised so "Star Wars" and "star wars " are one tag.
        CheckConstraint("tag = lower(btrim(tag)) AND length(tag) > 0", name="tag_normalised"),
    )


class Metric(Base):
    """The metric catalog: what each metric key means. Shared reference data, not per client."""

    __tablename__ = "metric"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text)
    family: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(Text)
    # How values combine across videos: sum them, recompute a ratio from two metrics,
    # average them weighted by another metric, or do not combine at all (for example unique viewers).
    aggregation: Mapped[str] = mapped_column(Text)
    numerator_key: Mapped[str | None] = mapped_column(ForeignKey("metric.key"))
    denominator_key: Mapped[str | None] = mapped_column(ForeignKey("metric.key"))
    weight_key: Mapped[str | None] = mapped_column(ForeignKey("metric.key"))
    description: Mapped[str | None] = mapped_column(Text)
    # Columns the importer did not recognise are kept but flagged until someone classifies them.
    review_status: Mapped[str] = mapped_column(Text, server_default="reviewed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("key ~ '^[a-z][a-z0-9_]*$'", name="key_format"),
        CheckConstraint(_in("unit", METRIC_UNITS), name="unit_known"),
        CheckConstraint(_in("aggregation", METRIC_AGGREGATIONS), name="aggregation_known"),
        CheckConstraint(_in("review_status", REVIEW_STATUSES), name="review_status_known"),
        CheckConstraint(
            "(aggregation = 'ratio') = (numerator_key IS NOT NULL AND denominator_key IS NOT NULL)",
            name="ratio_needs_both_keys",
        ),
        CheckConstraint("(aggregation = 'weighted_avg') = (weight_key IS NOT NULL)", name="weighted_needs_weight"),
    )


class MetricAlias(Base):
    """Maps a column header as it appears in an export to a catalog metric."""

    __tablename__ = "metric_alias"

    # Normalised header: lower case, whitespace collapsed. "Impressions click-through rate (%)" is stored
    # as "impressions click-through rate (%)".
    alias: Mapped[str] = mapped_column(Text, primary_key=True)
    metric_key: Mapped[str] = mapped_column(ForeignKey("metric.key", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("alias = lower(btrim(alias))", name="alias_normalised"),
        Index("ix_metric_alias_metric_key", "metric_key"),
    )


class VideoMetric(Base):
    """One number: this video, in this upload, for this metric. A missing row means 'not reported'."""

    __tablename__ = "video_metric"

    upload_id: Mapped[int] = mapped_column(BigInteger)
    video_id: Mapped[int] = mapped_column(BigInteger)
    metric_key: Mapped[str] = mapped_column(ForeignKey("metric.key"))
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    value: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        PrimaryKeyConstraint("upload_id", "video_id", "metric_key", name="pk_video_metric"),
        ForeignKeyConstraint(
            ["client_id", "upload_id"], ["upload.client_id", "upload.id"],
            ondelete="CASCADE",
            name="fk_video_metric_upload",
        ),
        ForeignKeyConstraint(
            ["client_id", "video_id"], ["video.client_id", "video.id"],
            ondelete="CASCADE",
            name="fk_video_metric_video",
        ),
        CheckConstraint("abs(value) < 'Infinity'::float8", name="value_finite"),
        # "How did this video's metric change from one upload to the next?"
        Index("ix_video_metric_history", "video_id", "metric_key", "upload_id"),
    )


class UploadTotal(Base):
    """The channel-wide 'Total' row of an export. It is a summary of videos, not a video itself."""

    __tablename__ = "upload_total"

    upload_id: Mapped[int] = mapped_column(BigInteger)
    metric_key: Mapped[str] = mapped_column(ForeignKey("metric.key"))
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    value: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        PrimaryKeyConstraint("upload_id", "metric_key", name="pk_upload_total"),
        ForeignKeyConstraint(
            ["client_id", "upload_id"], ["upload.client_id", "upload.id"],
            ondelete="CASCADE",
            name="fk_upload_total_upload",
        ),
        CheckConstraint("abs(value) < 'Infinity'::float8", name="value_finite"),
    )
