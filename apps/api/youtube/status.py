"""Which clients' stored YouTube data needs attention, and deleting it by hand.

Refreshing and deleting are manual for now (automation comes later), so the UI needs to be told when to ask.
Data that has expired is already hidden from the analyses; "expiring" is the warning before that happens.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from db.models import Client, Video, VideoPublicMetadata, VideoTag

WARN_BEFORE = timedelta(days=7)


@dataclass(frozen=True)
class PublicDataAlert:
    client_id: uuid.UUID
    client_name: str
    stored: int
    expired: int
    expiring_soon: int
    next_expiry: datetime | None

    @property
    def level(self) -> str:
        return "expired" if self.expired else "expiring"


def alerts(session: Session) -> list[PublicDataAlert]:
    """Clients with stored YouTube data that has expired or will within a week. Most urgent first."""
    meta = VideoPublicMetadata
    rows = session.execute(
        select(
            Client.id, Client.name,
            func.count().label("stored"),
            func.count().filter(meta.expires_at <= func.now()).label("expired"),
            func.count().filter(
                (meta.expires_at > func.now()) & (meta.expires_at <= func.now() + WARN_BEFORE)
            ).label("soon"),
            func.min(meta.expires_at).label("next_expiry"),
        )
        .join(Video, Video.client_id == Client.id)
        .join(meta, (meta.client_id == Video.client_id) & (meta.video_id == Video.id))
        .group_by(Client.id, Client.name)
    ).all()
    found = [PublicDataAlert(*row) for row in rows if row.expired or row.soon]
    return sorted(found, key=lambda a: (not a.expired, a.next_expiry))


def delete_public_data(session: Session, client_id: uuid.UUID) -> int:
    """Erase all stored YouTube data for a client (the export data is untouched). Returns the videos affected."""
    session.execute(delete(VideoTag).where(VideoTag.client_id == client_id))
    result = session.execute(delete(VideoPublicMetadata).where(VideoPublicMetadata.client_id == client_id))
    return result.rowcount
