"""Pull what clients uploaded to the portal inbox into the admin app, through the same checks as any upload.

Nothing is pushed in: the admin app reaches out. Each file is judged on its own, so one bad file never blocks the rest.
The client's file name and claimed hash are untrusted; the path, size, type and content are all re-checked here.
"""
import hashlib
import os
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from config import settings
from db.models import Client
from ingest.importer import ImportRejected, import_export
from portal import client as portal

ALLOWED_SUFFIXES = {".csv", ".xlsx"}  # not .xlsm: macros have no place in a client upload
MAX_UNZIPPED_BYTES = 100 * 1024 * 1024  # an .xlsx is a zip; refuse one that expands absurdly


@dataclass
class PullOutcome:
    inbox_id: int
    client_name: str | None
    filename: str
    result: str  # imported | duplicate | rejected | skipped
    detail: str


def _verdict(session: Session, row: dict) -> tuple[str, str, bytes | None]:
    """Decide what to do with one inbox row. Returns (result, detail, file bytes if it should be imported)."""
    client_id = uuid.UUID(row["client_id"])
    if session.get(Client, client_id) is None:
        return "skipped", "This client no longer exists here.", None
    if not portal.safe_storage_path(client_id, row["storage_path"]):
        return "rejected", "The upload could not be accepted.", None
    suffix = Path(row["original_filename"]).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        return "rejected", "Please upload a .csv or .xlsx file exported from YouTube Studio.", None
    if row["size_bytes"] > settings.max_upload_bytes:
        return "rejected", f"The file is larger than {settings.max_upload_mb} MB.", None
    try:
        data = portal.download_file(row["storage_path"])
    except portal.PortalError as exc:
        return "skipped", str(exc), None
    if len(data) > settings.max_upload_bytes:
        return "rejected", f"The file is larger than {settings.max_upload_mb} MB.", None
    if hashlib.sha256(data).hexdigest() != row["sha256"]:
        return "rejected", "The file did not arrive intact. Please upload it again.", None
    return "ok", "", data


def _import(session: Session, row: dict, data: bytes) -> tuple[str, str]:
    suffix = Path(row["original_filename"]).suffix.lower()
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        if suffix == ".xlsx":
            try:
                with zipfile.ZipFile(path) as archive:
                    if sum(info.file_size for info in archive.infolist()) > MAX_UNZIPPED_BYTES:
                        return "rejected", "The file is not a normal spreadsheet."
            except zipfile.BadZipFile:
                return "rejected", "That file is not a readable spreadsheet."
        try:
            with session.begin_nested():  # a failed import undoes only this file
                result = import_export(
                    session, client_id=uuid.UUID(row["client_id"]), path=path,
                    filename=row["original_filename"], sha256=hashlib.sha256(data).hexdigest(),
                    max_rows=settings.max_rows,
                )
        except ImportRejected as exc:
            return "rejected", str(exc)[:250]
        if result.duplicate:
            return "duplicate", "This file had already been imported."
        return "imported", f"Imported {result.videos} videos."
    finally:
        os.unlink(path)


def pull_inbox(session: Session) -> list[PullOutcome]:
    """Import every pending upload, tell the client the outcome, and remove the file from the portal."""
    outcomes = []
    names = {c.id: c.name for c in session.query(Client)}
    for row in portal.list_inbox("pending"):
        result, detail, data = _verdict(session, row)
        if data is not None:
            result, detail = _import(session, row, data)
        outcomes.append(PullOutcome(row["id"], names.get(uuid.UUID(row["client_id"])), row["original_filename"],
                                    result, detail))
        if result == "skipped":
            continue  # not the file's fault (portal hiccup, unknown client): leave it pending
        portal.set_inbox_result(row["id"], "rejected" if result == "rejected" else "pulled", detail)
        if portal.safe_storage_path(uuid.UUID(row["client_id"]), row["storage_path"]):
            try:
                portal.delete_file(row["storage_path"])
            except portal.PortalError:
                pass  # already gone; the row is marked, so it will not be pulled again
    return outcomes
