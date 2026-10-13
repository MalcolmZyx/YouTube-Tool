"""Read a client's stored export back out of the database as a table the analyses understand."""
import uuid

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Metric, Upload, UploadTotal, Video, VideoMetric

# The descriptive columns come first and use the names Studio uses, so the analyses and the UI see the same
# column names whether the table came from a spreadsheet or from the database.
ID_COLUMN, TITLE_COLUMN, PUBLISHED_COLUMN, DURATION_COLUMN = "Content", "Video title", "Video publish time", "Duration"


class NoUpload(LookupError):
    """The client has no upload (or not the requested one)."""


def pick_upload(session: Session, client_id: uuid.UUID, upload_id: int | None) -> Upload:
    """The requested upload, or the client's most recent one. Always scoped to the client."""
    query = select(Upload).where(Upload.client_id == client_id, Upload.report_type == "table_data")
    if upload_id is not None:
        query = query.where(Upload.id == upload_id)
    upload = session.scalar(query.order_by(Upload.imported_at.desc(), Upload.id.desc()).limit(1))
    if upload is None:
        raise NoUpload("No data uploaded for this client yet." if upload_id is None else "Upload not found")
    return upload


def load_table(session: Session, upload: Upload) -> tuple[pd.DataFrame, pd.Series | None]:
    """One row per video with a column per metric, and the Total row, both with metric display names.

    A metric nobody reported is simply absent (a blank cell), never 0. Videos that have no value in this upload
    are not listed.
    """
    values = session.execute(
        select(
            Video.youtube_video_id, Video.title, Video.published_on, Video.duration_seconds,
            Metric.display_name, Metric.family, Metric.key, VideoMetric.value,
        )
        .join(Video, (Video.client_id == VideoMetric.client_id) & (Video.id == VideoMetric.video_id))
        .join(Metric, Metric.key == VideoMetric.metric_key)
        .where(VideoMetric.upload_id == upload.id, VideoMetric.client_id == upload.client_id)
    ).all()
    if not values:
        return pd.DataFrame(columns=[ID_COLUMN]), None

    long = pd.DataFrame(values, columns=["id", "title", "published", "duration", "metric", "family", "key", "value"])
    order = long[["metric", "family", "key"]].drop_duplicates().sort_values(["family", "key"])["metric"].tolist()
    table = long.pivot(index="id", columns="metric", values="value")[order]
    info = long.drop_duplicates("id").set_index("id")[["title", "published", "duration"]]

    frame = pd.DataFrame({
        ID_COLUMN: table.index,
        TITLE_COLUMN: info.loc[table.index, "title"].to_numpy(),
        PUBLISHED_COLUMN: pd.to_datetime(info.loc[table.index, "published"]).to_numpy(),
        DURATION_COLUMN: info.loc[table.index, "duration"].to_numpy(),
    })
    frame = pd.concat([frame, table.reset_index(drop=True)], axis=1)
    if "Views" in frame.columns:
        frame = frame.sort_values("Views", ascending=False, na_position="last").reset_index(drop=True)

    totals = session.execute(
        select(Metric.display_name, UploadTotal.value)
        .join(Metric, Metric.key == UploadTotal.metric_key)
        .where(UploadTotal.upload_id == upload.id, UploadTotal.client_id == upload.client_id)
    ).all()
    total_row = None
    if totals:
        total_row = pd.Series({ID_COLUMN: "Total", **dict(totals)}).reindex(frame.columns)
    return frame, total_row
