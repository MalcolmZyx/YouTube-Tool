"""Talk to the portal database over Supabase's REST API with the service key.

The service key bypasses row-level security, so it exists only in the admin app's environment (PORTAL_SERVICE_KEY).
It is never logged, never put in an error message, and never sent to a browser.
"""
import json
import math
import os
from datetime import date, datetime
from typing import Any

import requests

from config import settings

TIMEOUT = 20
MAX_PAYLOAD_BYTES = 5 * 1024 * 1024  # per snapshot; the admin app caps exports at 5 MB, so this is generous


class PortalError(Exception):
    """The portal could not be reached or refused the request. The message is safe to show."""


class PortalNotConfigured(PortalError):
    pass


class PayloadTooLarge(PortalError):
    pass


def get_service_key() -> str:
    return os.environ.get("PORTAL_SERVICE_KEY", "")


def is_configured() -> bool:
    return bool(settings.portal_url and get_service_key())


def _clean(value: Any) -> Any:
    """Make a value storable as JSON: NaN and infinity become null, dates become text."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _request(method: str, path: str, *, params=None, body=None, prefer: str | None = None) -> requests.Response:
    if not is_configured():
        raise PortalNotConfigured("The portal is not configured (set PORTAL_URL and PORTAL_SERVICE_KEY in .env).")
    key = get_service_key()
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    try:
        response = requests.request(
            method, f"{settings.portal_url.rstrip('/')}/rest/v1/{path}", params=params, headers=headers,
            data=None if body is None else json.dumps(body, allow_nan=False), timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        # The exception text can contain the URL; say only what kind of failure it was.
        raise PortalError(f"Could not reach the portal ({type(exc).__name__}).") from None
    if response.status_code >= 400:
        raise PortalError(f"The portal refused the request (HTTP {response.status_code}).")
    return response


def publish(client_id, display_name: str, snapshots: dict[str, dict], as_of: date | None) -> None:
    """Create or update the client's portal record and replace its snapshots. `snapshots` maps kind to payload."""
    rows = []
    for kind, payload in snapshots.items():
        cleaned = _clean(payload)
        if len(json.dumps(cleaned, allow_nan=False).encode()) > MAX_PAYLOAD_BYTES:
            raise PayloadTooLarge(f"The {kind} snapshot is larger than {MAX_PAYLOAD_BYTES // 1024 // 1024} MB.")
        rows.append({
            "client_id": str(client_id), "kind": kind, "payload": cleaned,
            "as_of": as_of.isoformat() if as_of else None, "published_at": datetime.now().astimezone().isoformat(),
        })
    merge = "resolution=merge-duplicates,return=minimal"
    _request("POST", "portal_client", params={"on_conflict": "id"}, prefer=merge,
             body={"id": str(client_id), "display_name": display_name})
    _request("POST", "published_snapshot", params={"on_conflict": "client_id,kind"}, prefer=merge, body=rows)


def unpublish(client_id) -> None:
    """Remove the client from the portal: its snapshots, requests, permissions and memberships go with it."""
    _request("DELETE", "portal_client", params={"id": f"eq.{client_id}"})


def status(client_id) -> dict[str, str]:
    """When each snapshot kind was last published (empty if never)."""
    response = _request("GET", "published_snapshot",
                        params={"client_id": f"eq.{client_id}", "select": "kind,published_at,as_of"})
    return {row["kind"]: row["published_at"] for row in response.json()}


# ── what clients create in the portal: requests, permissions, preferences ───────────────────────────────────────────
# Request notes are written by clients, so they are untrusted text: stored and shown as text, never interpreted.

REQUEST_STATUSES = ("requested", "approved", "declined", "done")
PERMISSION_STATUSES = ("requested", "granted", "denied", "expired")


def list_requests(statuses: tuple[str, ...] | None = None) -> list[dict]:
    """Requests from every client, newest first. `statuses` filters (default: all)."""
    params = {
        "select": "id,client_id,type,note,status,created_at,updated_at", "order": "created_at.desc", "limit": "500",
    }
    if statuses:
        params["status"] = f"in.({','.join(statuses)})"
    return _request("GET", "service_request", params=params).json()


def set_request_status(request_id: int, new_status: str) -> dict | None:
    """Change a request's status. Returns the updated row, or None if no such request."""
    response = _request(
        "PATCH", "service_request", params={"id": f"eq.{request_id}"}, prefer="return=representation",
        body={"status": new_status, "updated_at": datetime.now().astimezone().isoformat()},
    )
    rows = response.json()
    return rows[0] if rows else None


def list_permissions(client_id) -> list[dict]:
    response = _request("GET", "client_permission", params={
        "client_id": f"eq.{client_id}", "select": "feature,status,quota,expires_at", "order": "feature"})
    return response.json()


def set_permission(client_id, feature: str, new_status: str, quota: int | None, expires_at: datetime | None) -> None:
    """Create or replace one permission for a client."""
    _request("POST", "client_permission", params={"on_conflict": "client_id,feature"},
             prefer="resolution=merge-duplicates,return=minimal", body={
                 "client_id": str(client_id), "feature": feature, "status": new_status, "quota": quota,
                 "expires_at": expires_at.isoformat() if expires_at else None})


def delete_permission(client_id, feature: str) -> None:
    _request("DELETE", "client_permission", params={"client_id": f"eq.{client_id}", "feature": f"eq.{feature}"})


def get_preference(client_id) -> dict:
    """What the client chose to focus on (empty if they have not chosen)."""
    rows = _request("GET", "dashboard_preference",
                    params={"client_id": f"eq.{client_id}", "select": "focus,updated_at"}).json()
    return rows[0] if rows else {"focus": {}, "updated_at": None}
