"""YouTube API quota left today, and which clients' stored YouTube data needs a manual refresh or delete."""
from fastapi import APIRouter

import deps
from schemas import PublicDataAlertOut, QuotaOut
from youtube import quota
from youtube.status import alerts

router = APIRouter(tags=["youtube"])


@router.get("/quota", response_model=QuotaOut)
def get_quota(session: deps.SessionDep) -> QuotaOut:
    """The quota this app has spent today (YouTube's day, Pacific time) and what is left. An estimate."""
    status = quota.get_status(session)
    return QuotaOut(
        limit=status.limit, used_today=status.used_today, remaining=status.remaining,
        used_last_7_days=status.used_last_7_days, resets_at=status.resets_at,
    )


@router.get("/public-data/alerts", response_model=list[PublicDataAlertOut])
def public_data_alerts(session: deps.SessionDep) -> list[PublicDataAlertOut]:
    """Clients whose stored YouTube data has expired (hidden) or expires within 7 days. Refreshing is manual."""
    return [
        PublicDataAlertOut(
            client_id=a.client_id, client_name=a.client_name, level=a.level, stored=a.stored,
            expired=a.expired, expiring_soon=a.expiring_soon, next_expiry=a.next_expiry,
        )
        for a in alerts(session)
    ]
