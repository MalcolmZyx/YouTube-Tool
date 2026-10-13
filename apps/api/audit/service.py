"""Build an audit for a client's upload from the database."""
import uuid
from dataclasses import asdict
from datetime import date

from sqlalchemy.orm import Session

from audit.engine import ID, Context, run_audit
from db.models import Upload
from services.client_data import load_table, pick_upload


def as_of_date(upload: Upload) -> tuple[date, str]:
    """The date video ages are measured against, and where it came from.

    A stated or file-name date range ends on the export date; otherwise the day it was imported is the best guess.
    """
    if upload.period_kind == "range" and upload.period_end:
        return upload.period_end, "the end of the export's date range"
    if upload.exported_on:
        return upload.exported_on, "the export date you gave"
    return upload.imported_at.date(), "the day the file was imported (the export's own date is unknown)"


def build_audit(session: Session, client_id: uuid.UUID, upload_id: int | None = None) -> dict:
    upload = pick_upload(session, client_id, upload_id)
    frame, total_row = load_table(session, upload)
    as_of, as_of_source = as_of_date(upload)
    totals = {} if total_row is None else {k: float(v) for k, v in total_row.items() if k != ID and v == v}
    findings = run_audit(Context(frame=frame, totals=totals, as_of=as_of, period_kind=upload.period_kind))
    return {
        "upload_id": upload.id,
        "filename": upload.original_filename,
        "period_kind": upload.period_kind,
        "as_of": as_of,
        "as_of_source": as_of_source,
        "videos": len(frame),
        "findings": [asdict(f) for f in findings],
    }
