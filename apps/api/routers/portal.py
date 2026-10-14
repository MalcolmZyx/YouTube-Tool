"""Publish a client's finished results to the hosted portal, and take them down again."""
import uuid

from fastapi import APIRouter, HTTPException

import deps
from portal import client as portal
from portal.publish import publish_client
from routers.clients import _get_client
from schemas import PortalStatusOut
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
