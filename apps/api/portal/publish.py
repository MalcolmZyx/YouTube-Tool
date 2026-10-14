"""Build what gets published: the audit and the dashboard table, from the creator's own export only.

Deliberately left out: anything fetched from the YouTube API (tags, descriptions, thumbnails). It must be refreshed or
deleted within 30 days, and a published copy would need the same expiry. The upload's file name is left out too.
"""
import uuid

from sqlalchemy.orm import Session

import deps
from audit.service import as_of_date, build_audit
from db.models import Client
from portal import client as portal
from services.client_data import load_table, pick_upload

# Columns build_dataset adds for API enrichment; they are empty here and must not be published.
_API_COLUMNS = ("thumbnail_url", "video_description", "video_title")


def dashboard_payload(session: Session, client_id: uuid.UUID, upload_id: int | None = None) -> dict:
    upload = pick_upload(session, client_id, upload_id)
    frame, total_row = load_table(session, upload)
    dataset = deps.data_svc.build_dataset(frame, total_row)
    rows = [{k: v for k, v in row.items() if k not in _API_COLUMNS} for row in dataset["rows"]]
    total = dataset["total_row"]
    return {
        "rows": rows,
        "total_row": None if total is None else {k: v for k, v in total.items() if k not in _API_COLUMNS},
        "columns": [c for c in dataset["columns"] if c not in _API_COLUMNS],
        "numeric_columns": dataset["numeric_columns"],
        "percent_columns": dataset["percent_columns"],
        "video_id_col": dataset["video_id_col"],
    }


def audit_payload(session: Session, client_id: uuid.UUID, upload_id: int | None = None) -> dict:
    audit = build_audit(session, client_id, upload_id)
    return {k: v for k, v in audit.items() if k not in ("filename", "upload_id")}


def publish_client(session: Session, client: Client, upload_id: int | None = None) -> dict[str, str]:
    """Publish the client's latest (or chosen) upload. Raises NoUpload, PortalError."""
    upload = pick_upload(session, client.id, upload_id)
    snapshots = {
        "audit": audit_payload(session, client.id, upload.id),
        "dashboard": dashboard_payload(session, client.id, upload.id),
    }
    portal.publish(client.id, client.name, snapshots, as_of_date(upload)[0])
    return portal.status(client.id)
