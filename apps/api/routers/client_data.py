"""A client's stored export, served to the dashboard and the analyses (the database-backed twin of /api/dashboard)."""
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

import deps
from audit.report import render_html
from audit.service import build_audit
from routers.analysis import make_router
from routers.clients import SessionDep, _get_client
from schemas import AuditOut, DatasetOut, EnrichOut, PublicDataDeletedOut
from services.client_data import NoUpload, load_table, pick_upload
from youtube import quota, store
from youtube.client import BATCH_SIZE, QuotaExceeded, YouTubeError


def get_client_dataset(client_id: uuid.UUID, session: SessionDep, upload_id: int | None = None) -> dict[str, Any]:
    """Dependency: the client's dataset from the database. `upload_id` picks an upload; default is the latest."""
    _get_client(session, client_id)
    try:
        upload = pick_upload(session, client_id, upload_id)
    except NoUpload as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    frame, total_row = load_table(session, upload)
    dataset = deps.data_svc.build_dataset(frame, total_row)
    _attach_public_data(dataset, _public_data(client_id))
    return dataset


def _public_data(client_id: uuid.UUID) -> dict[str, dict]:
    """The stored YouTube details, or none: they only enrich Keywords and Descriptions, so a store that is not set
    up (or is down) must not break the dashboard."""
    try:
        return store.load_public_data(client_id)
    except store.StoreError:
        return {}


def _attach_public_data(dataset: dict[str, Any], public: dict[str, dict]) -> None:
    """Add the stored (unexpired) YouTube details to the rows, as the keyword and description analyses expect."""
    id_col = dataset["video_id_col"]
    metadata = []
    for row in dataset["rows"]:
        info = public.get(str(row.get(id_col, "")).strip())
        if info:
            row["video_description"] = info["description"]
            row["thumbnail_url"] = info["thumbnail_url"]
            metadata.append({"video_id": row[id_col], "tags": info["tags"], "category_id": info["category_id"]})
    dataset["metadata"] = metadata


router = APIRouter(prefix="/clients/{client_id}")
router.include_router(make_router(get_client_dataset))


@router.get("/dashboard", response_model=DatasetOut, tags=["clients"])
def client_dashboard(dataset: Annotated[dict[str, Any], Depends(get_client_dataset)]) -> dict:
    """The client's table: videos, the Total row and the columns the UI should show."""
    return dataset


@router.post("/enrich", response_model=EnrichOut, tags=["clients"])
def enrich_client(client_id: uuid.UUID, session: SessionDep, api_key: deps.ApiKey, force: bool = False) -> EnrichOut:
    """Fetch public YouTube details (description, tags, thumbnail) for this client's videos.

    Only videos with no data, or data older than a week, are fetched unless `force` is set. Stored data
    expires after 30 days (YouTube's rule for public data); see youtube/store.py.
    """
    _get_client(session, client_id)
    try:
        due = store.videos_due(session, client_id, force)
    except store.StoreNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except store.StoreError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    needed = -(-len(due) // BATCH_SIZE) * quota.COST_VIDEOS_LIST  # ceil division
    left = quota.get_status(session).remaining
    if needed > left:
        raise HTTPException(
            status_code=429, detail=f"Not enough YouTube quota left today (needs about {needed} units, {left} left)."
        )
    try:
        result = store.refresh_client(session, client_id, api_key, force=force)
    except store.StoreError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except QuotaExceeded as exc:
        quota.mark_exhausted(session)
        session.commit()  # the error below would otherwise roll this back
        raise HTTPException(status_code=429, detail=str(exc)) from None
    except YouTubeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    quota.record(session, needed)
    return EnrichOut(requested=result.requested, stored=result.stored, unavailable=result.unavailable)


@router.delete("/public-data", response_model=PublicDataDeletedOut, tags=["clients"])
def delete_client_public_data(client_id: uuid.UUID, session: SessionDep) -> PublicDataDeletedOut:
    """Erase the stored YouTube details (tags, descriptions, thumbnails) for this client. The export is kept."""
    _get_client(session, client_id)
    try:
        return PublicDataDeletedOut(deleted_videos=store.delete_client_data(client_id))
    except store.StoreNotConfigured:
        return PublicDataDeletedOut(deleted_videos=0)  # nothing is stored without a store
    except store.StoreError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@router.get("/audit", response_model=AuditOut, tags=["audit"])
def client_audit(client_id: uuid.UUID, session: SessionDep, upload_id: int | None = None) -> dict:
    """Findings about the channel, with evidence and caveats, computed from the stored export."""
    _get_client(session, client_id)
    try:
        return build_audit(session, client_id, upload_id)
    except NoUpload as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.get("/audit/report", response_class=HTMLResponse, tags=["audit"])
def client_audit_report(client_id: uuid.UUID, session: SessionDep, upload_id: int | None = None) -> HTMLResponse:
    """The audit as one self-contained HTML page (no scripts), downloadable, printable to PDF."""
    client = _get_client(session, client_id)
    try:
        audit = build_audit(session, client_id, upload_id)
    except NoUpload as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    name = "".join(c if c.isalnum() else "-" for c in client.name).strip("-").lower() or "client"
    return HTMLResponse(
        render_html(audit, client.name),
        headers={
            "Content-Disposition": f'attachment; filename="audit-{name}.html"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        },
    )
