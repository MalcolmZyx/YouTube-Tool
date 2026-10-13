"""Keep public API data for at most 30 days: store it with an expiry, refresh what is due, delete what expired.

This is the structure that keeps us inside YouTube's rule for non-authorized data (Developer Policies III.E.4.d):
every stored row has `expires_at`, `refresh_client` renews it, and `purge_expired` deletes what was not renewed.
"""
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from db.models import Video, VideoPublicMetadata, VideoTag
from youtube.client import VideoInfo, fetch_videos

RETENTION = timedelta(days=30)
REFRESH_AFTER = timedelta(days=7)  # renewed well before expiry, so a missed run does not lose data

Fetcher = Callable[[Iterable[str], str], dict[str, VideoInfo]]


@dataclass
class RefreshResult:
    requested: int = 0
    stored: int = 0
    unavailable: int = 0  # private, deleted or unknown videos: nothing public to store


def _normalise_tags(tags: Iterable[str]) -> set[str]:
    return {t.strip().lower() for t in tags if t and t.strip()}


def videos_due(session: Session, client_id: uuid.UUID, force: bool = False) -> list[tuple[int, str]]:
    """(row id, YouTube ID) of the client's videos with no public data yet, or data older than REFRESH_AFTER."""
    query = (
        select(Video.id, Video.youtube_video_id)
        .outerjoin(VideoPublicMetadata, (VideoPublicMetadata.client_id == Video.client_id)
                   & (VideoPublicMetadata.video_id == Video.id))
        .where(Video.client_id == client_id)
        .order_by(Video.id)
    )
    if not force:
        query = query.where(
            VideoPublicMetadata.video_id.is_(None) | (VideoPublicMetadata.fetched_at < func.now() - REFRESH_AFTER)
        )
    return [(row_id, youtube_id) for row_id, youtube_id in session.execute(query)]


def refresh_client(
    session: Session, client_id: uuid.UUID, api_key: str, fetch: Fetcher = fetch_videos, force: bool = False
) -> RefreshResult:
    """Fetch public details for the client's videos that need them and store them for 30 days."""
    due = videos_due(session, client_id, force)
    result = RefreshResult(requested=len(due))
    if not due:
        return result

    found = fetch([youtube_id for _, youtube_id in due], api_key)
    for row_id, youtube_id in due:
        info = found.get(youtube_id)
        values = {
            "client_id": client_id, "video_id": row_id,
            "description": info.description if info else None,
            "thumbnail_url": info.thumbnail_url if info else None,
            "category_id": info.category_id if info else None,
            "published_at": info.published_at if info else None,
            "availability": "public" if info else "unavailable",
            "fetched_at": func.now(), "expires_at": func.now() + RETENTION,
        }
        statement = insert(VideoPublicMetadata).values(**values)
        session.execute(statement.on_conflict_do_update(
            index_elements=[VideoPublicMetadata.video_id],
            set_={k: v for k, v in values.items() if k not in ("client_id", "video_id")},
        ))
        session.execute(delete(VideoTag).where(VideoTag.client_id == client_id, VideoTag.video_id == row_id))
        if info:
            session.add_all(VideoTag(client_id=client_id, video_id=row_id, tag=t) for t in _normalise_tags(info.tags))
            result.stored += 1
        else:
            result.unavailable += 1
    return result


def purge_expired(session: Session) -> int:
    """Delete public data past its expiry (and its tags). Returns the number of videos purged. Run daily."""
    expired = select(VideoPublicMetadata.client_id, VideoPublicMetadata.video_id).where(
        VideoPublicMetadata.expires_at <= func.now()
    )
    rows = session.execute(expired).all()
    for client_id, video_id in rows:
        session.execute(delete(VideoTag).where(VideoTag.client_id == client_id, VideoTag.video_id == video_id))
        session.execute(delete(VideoPublicMetadata).where(VideoPublicMetadata.video_id == video_id))
    return len(rows)


def load_public_data(session: Session, client_id: uuid.UUID) -> dict[str, dict]:
    """Unexpired public data by YouTube ID: description, thumbnail, category and tags. Expired rows are ignored."""
    rows = session.execute(
        select(Video.id, Video.youtube_video_id, VideoPublicMetadata.description,
               VideoPublicMetadata.thumbnail_url, VideoPublicMetadata.category_id)
        .join(VideoPublicMetadata, (VideoPublicMetadata.client_id == Video.client_id)
              & (VideoPublicMetadata.video_id == Video.id))
        .where(Video.client_id == client_id, VideoPublicMetadata.availability == "public",
               VideoPublicMetadata.expires_at > func.now())
    ).all()
    tags: dict[int, list[str]] = {}
    for video_id, tag in session.execute(
        select(VideoTag.video_id, VideoTag.tag).where(VideoTag.client_id == client_id).order_by(VideoTag.tag)
    ):
        tags.setdefault(video_id, []).append(tag)
    return {
        youtube_id: {"description": description or "", "thumbnail_url": thumbnail or "",
                     "category_id": category, "tags": tags.get(row_id, [])}
        for row_id, youtube_id, description, thumbnail, category in rows
    }
