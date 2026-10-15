"""Which clients' stored YouTube data is about to expire, so it can be refreshed or deleted by hand.

MongoDB deletes each document by itself 30 days after it was fetched (the TTL index in store.py). That guarantees the
retention rule, but it also means data would silently vanish and the Keywords and Descriptions pages would go empty.
The alert gives a week's warning, with a button to refresh. Refreshing and deleting stay manual for now.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from pymongo.errors import PyMongoError
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Client
from youtube import store

WARN_BEFORE = timedelta(days=7)


@dataclass(frozen=True)
class PublicDataAlert:
    client_id: uuid.UUID
    client_name: str
    stored: int
    expired: int  # normally 0: expired documents are deleted within about a minute
    expiring_soon: int
    next_expiry: datetime | None

    @property
    def level(self) -> str:
        return "expired" if self.expired else "expiring"


def alerts(session: Session) -> list[PublicDataAlert]:
    """Clients whose stored YouTube data expires within a week (or already has). Most urgent first."""
    if not store.is_configured():
        return []
    now = store.utcnow()
    try:
        groups = store.collection().aggregate([{"$group": {
            "_id": "$client_id",
            "stored": {"$sum": 1},
            "expired": {"$sum": {"$cond": [{"$lte": ["$expires_at", now]}, 1, 0]}},
            "soon": {"$sum": {"$cond": [{"$and": [
                {"$gt": ["$expires_at", now]}, {"$lte": ["$expires_at", now + WARN_BEFORE]}]}, 1, 0]}},
            "next_expiry": {"$min": "$expires_at"},
        }}])
        rows = list(groups)
    except PyMongoError as exc:
        raise store.StoreError(f"Could not read from MongoDB ({type(exc).__name__}).") from None

    names = {str(c.id): (c.id, c.name) for c in session.scalars(select(Client))}
    found = [
        PublicDataAlert(names[r["_id"]][0], names[r["_id"]][1], r["stored"], r["expired"], r["soon"], r["next_expiry"])
        for r in rows if r["_id"] in names and (r["expired"] or r["soon"])
    ]
    return sorted(found, key=lambda a: (not a.expired, a.next_expiry))
