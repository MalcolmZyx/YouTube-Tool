"""Publish a client's finished results to the hosted portal, and take them down again."""
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from sqlalchemy import select

import deps
from db.models import Client
from portal import client as portal
from portal.publish import publish_client
from routers.clients import _get_client
from schemas import (
    PermissionIn,
    PermissionOut,
    PortalRequestOut,
    PortalStatusOut,
    PreferenceOut,
    RequestStatusIn,
)
from services.client_data import NoUpload

router = APIRouter(prefix="/clients/{client_id}/portal", tags=["portal"])


def _portal_error(exc: portal.PortalError) -> HTTPException:
    if isinstance(exc, portal.PortalNotConfigured):
        code = 503
    elif isinstance(exc, portal.PayloadTooLarge):
        code = 413
    else:
        code = 502
    return HTTPException(status_code=code, detail=str(exc))


@router.get("", response_model=PortalStatusOut)
def portal_status(client_id: uuid.UUID, session: deps.SessionDep) -> PortalStatusOut:
    """Whether the portal is configured, and when this client's snapshots were last published."""
    _get_client(session, client_id)
    if not portal.is_configured():
        return PortalStatusOut(configured=False, published={})
    try:
        return PortalStatusOut(configured=True, published=portal.status(client_id))
    except portal.PortalError as exc:
        raise _portal_error(exc) from None


@router.post("/publish", response_model=PortalStatusOut)
def publish(client_id: uuid.UUID, session: deps.SessionDep, upload_id: int | None = None) -> PortalStatusOut:
    """Copy the audit and the dashboard table (export data only) to the portal. Replaces the previous snapshots."""
    client = _get_client(session, client_id)
    try:
        return PortalStatusOut(configured=True, published=publish_client(session, client, upload_id))
    except NoUpload as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except portal.PortalError as exc:
        raise _portal_error(exc) from None


@router.delete("/publish", response_model=PortalStatusOut)
def unpublish(client_id: uuid.UUID, session: deps.SessionDep) -> PortalStatusOut:
    """Remove the client from the portal (its snapshots and anything the client created there)."""
    _get_client(session, client_id)
    try:
        portal.unpublish(client_id)
    except portal.PortalError as exc:
        raise _portal_error(exc) from None
    return PortalStatusOut(configured=True, published={})


# ── what clients create in the portal ───────────────────────────────────────────────────────────────────────────────
# Reading is on demand (nothing is pushed into this app). Statuses and permissions are decided here, in the admin app,
# with the service key; the portal only shows them.

requests_router = APIRouter(prefix="/portal", tags=["portal"])
FEATURE_PATTERN = r"^[a-z0-9_]{1,100}$"


@requests_router.get("/requests", response_model=list[PortalRequestOut])
def list_requests(session: deps.SessionDep, open_only: bool = False) -> list[PortalRequestOut]:
    """Requests clients made in the portal, newest first. `open_only` hides declined and finished ones."""
    try:
        rows = portal.list_requests(("requested", "approved") if open_only else None)
    except portal.PortalError as exc:
        raise _portal_error(exc) from None
    names = {c.id: c.name for c in session.scalars(select(Client))}
    return [PortalRequestOut(client_name=names.get(uuid.UUID(r["client_id"])), **r) for r in rows]


@requests_router.put("/requests/{request_id}", response_model=PortalRequestOut)
def set_request_status(request_id: int, body: RequestStatusIn, session: deps.SessionDep) -> PortalRequestOut:
    """Approve, decline or finish a request. The client sees the new status in the portal."""
    try:
        row = portal.set_request_status(request_id, body.status)
    except portal.PortalError as exc:
        raise _portal_error(exc) from None
    if row is None:
        raise HTTPException(status_code=404, detail="Request not found")
    client = session.get(Client, uuid.UUID(row["client_id"]))
    return PortalRequestOut(client_name=client.name if client else None, **row)


@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(client_id: uuid.UUID, session: deps.SessionDep) -> list[dict]:
    _get_client(session, client_id)
    try:
        return portal.list_permissions(client_id)
    except portal.PortalError as exc:
        raise _portal_error(exc) from None


@router.put("/permissions/{feature}", response_model=list[PermissionOut])
def set_permission(
    client_id: uuid.UUID, feature: Annotated[str, Path(pattern=FEATURE_PATTERN)], body: PermissionIn,
    session: deps.SessionDep,
) -> list[dict]:
    """Grant, deny or expire one feature for a client, with an optional quota and expiry."""
    _get_client(session, client_id)
    expires_at = datetime.now(UTC) + timedelta(days=body.expires_in_days) if body.expires_in_days else None
    try:
        portal.set_permission(client_id, feature, body.status, body.quota, expires_at)
        return portal.list_permissions(client_id)
    except portal.PortalError as exc:
        raise _portal_error(exc) from None


@router.delete("/permissions/{feature}", response_model=list[PermissionOut])
def delete_permission(
    client_id: uuid.UUID, feature: Annotated[str, Path(pattern=FEATURE_PATTERN)], session: deps.SessionDep
) -> list[dict]:
    _get_client(session, client_id)
    try:
        portal.delete_permission(client_id, feature)
        return portal.list_permissions(client_id)
    except portal.PortalError as exc:
        raise _portal_error(exc) from None


@router.get("/preferences", response_model=PreferenceOut)
def get_preferences(client_id: uuid.UUID, session: deps.SessionDep) -> dict:
    """What this client chose to focus on in the portal."""
    _get_client(session, client_id)
    try:
        return portal.get_preference(client_id)
    except portal.PortalError as exc:
        raise _portal_error(exc) from None
