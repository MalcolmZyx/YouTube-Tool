"""Count the YouTube API quota this app spends, so the UI can show what is left today.

The API never tells us the remaining quota, so this is our own count, and an estimate: it cannot see calls made
with the same key elsewhere. YouTube's quota day runs on Pacific time and resets at midnight there.

Costs (units), verified against developers.google.com/youtube/v3/determine_quota_cost: `videos.list`, `channels.list`,
`playlistItems.list` and `commentThreads.list` are 1 per request (`videos.list` takes up to 50 IDs). Since 2026-06-01
`search.list` is no longer 100 units of the main pool: it has its own bucket of 100 calls a day, 1 unit per call, so a
search never lowers the main meter. Writes and Analytics API calls are not used.
"""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Date, DateTime, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from config import settings
from db.models import ApiUsage

COST_VIDEOS_LIST = 1
COST_CHANNELS_LIST = 1
COST_PLAYLIST_ITEMS_LIST = 1
COST_COMMENT_THREADS_LIST = 1
COST_SEARCH_LIST = 1  # of the separate search bucket (100 calls a day, client.SEARCH_DAILY_CALLS), not the main pool
_QUOTA_TZ = "America/Los_Angeles"

# Postgres knows the time-zone rules, so the quota day is computed there, not guessed in Python.
_QUOTA_DAY = literal_column(f"(now() AT TIME ZONE '{_QUOTA_TZ}')::date", Date)
_RESET = literal_column(
    f"((now() AT TIME ZONE '{_QUOTA_TZ}')::date + 1)::timestamp AT TIME ZONE '{_QUOTA_TZ}'", DateTime(timezone=True)
)


@dataclass(frozen=True)
class QuotaStatus:
    limit: int
    used_today: int
    used_last_7_days: int  # including today
    resets_at: datetime

    @property
    def remaining(self) -> int:
        return max(self.limit - self.used_today, 0)


def record(session: Session, units: int) -> None:
    """Add spent units to today's count."""
    if units <= 0:
        return
    statement = insert(ApiUsage).values(day=_QUOTA_DAY, units=units)
    session.execute(statement.on_conflict_do_update(
        index_elements=[ApiUsage.day],
        set_={"units": ApiUsage.units + units, "updated_at": func.now()},
    ))


def mark_exhausted(session: Session) -> None:
    """YouTube said the quota is gone: make today's count say so, whatever we had counted."""
    limit = settings.youtube_daily_quota
    statement = insert(ApiUsage).values(day=_QUOTA_DAY, units=limit)
    session.execute(statement.on_conflict_do_update(
        index_elements=[ApiUsage.day],
        set_={"units": func.greatest(ApiUsage.units, limit), "updated_at": func.now()},
    ))


def get_status(session: Session) -> QuotaStatus:
    used_today = session.scalar(select(func.coalesce(func.sum(ApiUsage.units), 0)).where(ApiUsage.day == _QUOTA_DAY))
    used_week = session.scalar(
        select(func.coalesce(func.sum(ApiUsage.units), 0)).where(ApiUsage.day > _QUOTA_DAY - 7)
    )
    return QuotaStatus(
        limit=settings.youtube_daily_quota,
        used_today=used_today,
        used_last_7_days=used_week,
        resets_at=session.scalar(select(_RESET)),
    )
