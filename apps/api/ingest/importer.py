"""Importing a Studio export into the database.

`import_export` is the entry point. It runs inside the caller's transaction, so a failed import leaves
nothing behind, and it is idempotent: the same file (identified by its SHA-256) is never imported twice
for one client.

Each kind of export is a "report type" with a detector (does this file look like one?) and an importer.
Only the Content-tab "Table data" export exists today. A traffic-source or geography export is added by
writing another detector and importer and registering them in REPORT_TYPES, plus a table for its data.
"""
import logging
import re
import zipfile
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from itertools import batched
from pathlib import Path

import pandas as pd
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from db.catalog import ATTRIBUTE_HEADERS, find_metric_key, get_or_register_metric, normalize_header
from db.models import Metric, Upload, UploadTotal, Video, VideoMetric
from ingest.values import (
    is_blank,
    parse_date,
    parse_metric_value,
    parse_number,
    parse_period_from_filename,
)

logger = logging.getLogger(__name__)

_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_UNREADABLE = (ValueError, KeyError, IndexError, zipfile.BadZipFile, InvalidFileException)
_INSERT_BATCH = 2000
# Totals in an export often exceed the sum of the listed videos (deleted or hidden videos), so only a
# clear gap is worth mentioning.
_RECONCILE_TOLERANCE = 0.01


class ImportRejected(Exception):
    """The file cannot be imported. `status_code` is the HTTP status the API should answer with."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Period:
    """The date range an export covers. A Studio export does not say, so it is often unknown."""

    kind: str = "unknown"  # unknown | lifetime | range
    start: date | None = None
    end: date | None = None
    source: str | None = None  # filename | inferred | user


@dataclass
class ImportResult:
    upload_id: int
    duplicate: bool
    videos: int
    metric_values: int
    total_values: int
    period: Period
    new_unreviewed_metrics: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ImportContext:
    client_id: object  # uuid.UUID
    filename: str
    sha256: str
    period: Period
    exported_on: date | None
    max_rows: int | None


# ── reading ─────────────────────────────────────────────────────────────────


def read_export(path: str) -> pd.DataFrame:
    """Read a spreadsheet with every cell left as it came: Excel keeps its types, CSV stays text."""
    try:
        if Path(path).suffix.lower() in (".xlsx", ".xlsm"):
            df = pd.read_excel(path, engine="openpyxl", dtype=object)
        else:
            df = pd.read_csv(path, dtype=object)
    except _UNREADABLE as exc:
        logger.warning("Could not read export", exc_info=True)
        raise ImportRejected(
            "Could not read this file. Make sure it is a YouTube Studio export (.xlsx, .xlsm or .csv)."
        ) from exc
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all").dropna(axis=1, how="all")  # nothing to store in empty rows or columns
    if df.empty or len(df.columns) < 2:
        raise ImportRejected("This file has no data rows.")
    return df


# ── report types ────────────────────────────────────────────────────────────


def _looks_like_table_data(df: pd.DataFrame) -> bool:
    return normalize_header(df.columns[0]) == "content"


def _resolve_metrics(session: Session, columns: list[str], warnings: list[str]):
    """Map each metric column to a catalog key, registering unknown ones. Returns (keys, new_keys)."""
    keys: dict[str, str] = {}
    new_keys: list[str] = []
    for column in columns:
        known = find_metric_key(session, column)
        key = known or get_or_register_metric(session, column)
        if not known:
            new_keys.append(key)
        if key in keys.values():
            warnings.append(f"Column '{column}' is the same metric as an earlier column and was ignored.")
            continue
        keys[column] = key
    return keys, new_keys


def _import_table_data(session: Session, ctx: ImportContext, df: pd.DataFrame) -> ImportResult:
    id_col = df.columns[0]
    columns = list(df.columns[1:])
    attribute_cols = {normalize_header(c): c for c in columns if normalize_header(c) in ATTRIBUTE_HEADERS}
    metric_cols = [c for c in columns if normalize_header(c) not in ATTRIBUTE_HEADERS]
    warnings: list[str] = []

    # The "Total" row summarises the videos; it is not a video.
    ids = df[id_col].map(lambda v: "" if is_blank(v) else str(v).strip())
    is_total = ids.str.lower() == "total"
    total_row = df[is_total].iloc[0] if is_total.any() else None

    videos: list[tuple[str, pd.Series]] = []
    seen: set[str] = set()
    skipped: list[str] = []
    for youtube_id, (_, row) in zip(ids[~is_total], df[~is_total].iterrows(), strict=True):
        if not _YOUTUBE_ID.match(youtube_id):
            skipped.append(youtube_id or "(blank)")
        elif youtube_id in seen:
            warnings.append(f"Video {youtube_id} appears more than once; only the first row was used.")
        else:
            seen.add(youtube_id)
            videos.append((youtube_id, row))
    if skipped:
        shown = ", ".join(skipped[:5]) + (" ..." if len(skipped) > 5 else "")
        warnings.append(f"{len(skipped)} row(s) were skipped because their video ID is not valid: {shown}")
    if not videos:
        raise ImportRejected("No video rows were found in this file.")
    if ctx.max_rows is not None and len(videos) > ctx.max_rows:
        raise ImportRejected(f"This export has {len(videos):,} videos; the limit is {ctx.max_rows:,}.", 413)

    keys, new_keys = _resolve_metrics(session, metric_cols, warnings)

    upload = Upload(
        client_id=ctx.client_id,
        report_type="table_data",
        original_filename=ctx.filename,
        file_sha256=ctx.sha256,
        period_kind=ctx.period.kind,
        period_start=ctx.period.start,
        period_end=ctx.period.end,
        period_source=ctx.period.source,
        exported_on=ctx.exported_on,
        row_count=len(videos),
    )
    session.add(upload)
    session.flush()

    # Videos: create new ones, refresh the descriptive columns of ones seen in an earlier upload.
    def attribute(row: pd.Series, name: str):
        column = attribute_cols.get(name)
        return None if column is None else row[column]

    video_rows = []
    for youtube_id, row in videos:
        title = attribute(row, "video title")
        duration = parse_number(attribute(row, "duration"))
        video_rows.append(
            {
                "client_id": ctx.client_id,
                "youtube_video_id": youtube_id,
                "title": None if is_blank(title) else str(title).strip(),
                "published_on": parse_date(attribute(row, "video publish time")),
                "duration_seconds": None if duration is None or duration < 0 else round(duration),
            }
        )
    video_pk: dict[str, int] = {}
    for chunk in batched(video_rows, _INSERT_BATCH, strict=False):
        statement = insert(Video).values(list(chunk))
        statement = statement.on_conflict_do_update(
            index_elements=["client_id", "youtube_video_id"],
            # A blank in this export must not erase what an earlier export told us.
            set_={
                "title": func.coalesce(statement.excluded.title, Video.title),
                "published_on": func.coalesce(statement.excluded.published_on, Video.published_on),
                "duration_seconds": func.coalesce(statement.excluded.duration_seconds, Video.duration_seconds),
            },
        )
        for pk, youtube_id in session.execute(statement.returning(Video.id, Video.youtube_video_id)):
            video_pk[youtube_id] = pk

    # Metric values. A blank cell stores nothing ("not reported"); a 0 is stored as a real zero.
    unreadable: defaultdict[str, int] = defaultdict(int)
    metric_rows = []
    for youtube_id, row in videos:
        for column, key in keys.items():
            cell = row[column]
            value = parse_metric_value(cell)
            if value is not None:
                metric_rows.append(
                    {
                        "client_id": ctx.client_id,
                        "upload_id": upload.id,
                        "video_id": video_pk[youtube_id],
                        "metric_key": key,
                        "value": value,
                    }
                )
            elif not is_blank(cell):
                unreadable[column] += 1
    for chunk in batched(metric_rows, _INSERT_BATCH, strict=False):
        session.execute(insert(VideoMetric), list(chunk))

    total_rows = []
    if total_row is not None:
        for column, key in keys.items():
            value = parse_metric_value(total_row[column])
            if value is not None:
                total_rows.append(
                    {"client_id": ctx.client_id, "upload_id": upload.id, "metric_key": key, "value": value}
                )
        if total_rows:
            session.execute(insert(UploadTotal), total_rows)

    for column, count in unreadable.items():
        warnings.append(f"{count} cell(s) in column '{column}' were not numbers and were skipped.")
    warnings.extend(_reconcile(session, metric_rows, total_rows))
    if new_keys:
        warnings.append(
            f"{len(new_keys)} column(s) are new to the metric catalog and are marked unreviewed: " + ", ".join(new_keys)
        )

    return ImportResult(
        upload_id=upload.id,
        duplicate=False,
        videos=len(videos),
        metric_values=len(metric_rows),
        total_values=len(total_rows),
        period=ctx.period,
        new_unreviewed_metrics=new_keys,
        warnings=warnings,
    )


def _reconcile(session: Session, metric_rows: list[dict], total_rows: list[dict]) -> list[str]:
    """Warn where the videos clearly do not add up to the export's own Total row (additive metrics only)."""
    if not total_rows:
        return []
    totals = {r["metric_key"]: r["value"] for r in total_rows}
    sums: defaultdict[str, float] = defaultdict(float)
    for row in metric_rows:
        sums[row["metric_key"]] += row["value"]
    additive = session.execute(
        select(Metric.key, Metric.display_name).where(Metric.key.in_(totals), Metric.aggregation == "sum")
    )
    warnings = []
    for key, display_name in additive:
        total, summed = totals[key], sums.get(key, 0.0)
        if abs(summed - total) > max(1.0, _RECONCILE_TOLERANCE * abs(total)):
            warnings.append(
                f"{display_name}: the videos add up to {summed:,.0f} but the export's Total row says {total:,.0f}. "
                "The Total can include deleted videos and activity credited to the channel rather than a video."
            )
    return warnings


REPORT_TYPES: dict[str, tuple[Callable[[pd.DataFrame], bool], Callable[..., ImportResult]]] = {
    "table_data": (_looks_like_table_data, _import_table_data),
}


def detect_report_type(df: pd.DataFrame) -> str | None:
    return next((name for name, (looks_like, _) in REPORT_TYPES.items() if looks_like(df)), None)


# ── entry point ─────────────────────────────────────────────────────────────


def resolve_period(filename: str, explicit: Period | None) -> Period:
    """The period to record: what the user stated, else a range found in the file name, else unknown."""
    if explicit is not None:
        return explicit
    found = parse_period_from_filename(filename)
    return Period("range", found[0], found[1], "filename") if found else Period()


def _summarise_existing(session: Session, upload: Upload) -> ImportResult:
    metric_values = session.scalar(
        select(func.count()).select_from(VideoMetric).where(VideoMetric.upload_id == upload.id)
    )
    total_values = session.scalar(
        select(func.count()).select_from(UploadTotal).where(UploadTotal.upload_id == upload.id)
    )
    return ImportResult(
        upload_id=upload.id,
        duplicate=True,
        videos=upload.row_count,
        metric_values=metric_values,
        total_values=total_values,
        period=Period(upload.period_kind, upload.period_start, upload.period_end, upload.period_source),
        warnings=["This exact file was already imported; nothing was changed."],
    )


def import_export(
    session: Session,
    *,
    client_id,
    path: str,
    filename: str,
    sha256: str,
    period: Period | None = None,
    exported_on: date | None = None,
    max_rows: int | None = None,
) -> ImportResult:
    """Import one export file for one client. Raises ImportRejected if the file cannot be used."""
    existing = session.scalar(select(Upload).where(Upload.client_id == client_id, Upload.file_sha256 == sha256))
    if existing is not None:
        return _summarise_existing(session, existing)

    df = read_export(path)
    report_type = detect_report_type(df)
    if report_type is None:
        raise ImportRejected(
            f"Unrecognised export: the first column is '{df.columns[0]}'. Only the Content tab's "
            "'Table data' export (first column 'Content') is supported so far."
        )
    context = ImportContext(client_id, filename, sha256, resolve_period(filename, period), exported_on, max_rows)
    _, importer = REPORT_TYPES[report_type]
    return importer(session, context, df)
