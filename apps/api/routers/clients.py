"""Clients and their uploads: the persistent, per-client side of the API."""
import os
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Response, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

import deps
from config import settings
from db.models import Client, Upload, Video, VideoMetric
from ingest.importer import ImportRejected, Period, import_export
from intake import spool_upload
from schemas import ClientDeletedOut, ClientIn, ClientOut, ImportOut, PeriodIn, UploadOut

router = APIRouter(prefix="/clients", tags=["clients"])

SessionDep = deps.SessionDep


def _get_client(session: Session, client_id: uuid.UUID) -> Client:
    client = session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _count_for_client(model):
    """A correlated subquery: how many rows of `model` belong to the Client row of the outer query."""
    count = select(func.count()).select_from(model).where(model.client_id == Client.id)
    return count.correlate(Client).scalar_subquery()


def _clients_with_counts():
    """SELECT client, upload count, video count: one query, no per-client round trips."""
    return select(Client, _count_for_client(Upload), _count_for_client(Video))


def _client_out(client: Client, uploads: int, videos: int) -> ClientOut:
    return ClientOut(
        id=client.id,
        name=client.name,
        youtube_channel_id=client.youtube_channel_id,
        notes=client.notes,
        created_at=client.created_at,
        upload_count=uploads,
        video_count=videos,
    )


@router.post("", response_model=ClientOut, status_code=201)
def create_client(body: ClientIn, session: SessionDep) -> ClientOut:
    client = Client(name=body.name, youtube_channel_id=body.youtube_channel_id, notes=body.notes)
    session.add(client)
    session.flush()
    session.refresh(client)  # loads the database-generated id and created_at
    return _client_out(client, 0, 0)


@router.get("", response_model=list[ClientOut])
def list_clients(session: SessionDep) -> list[ClientOut]:
    rows = session.execute(_clients_with_counts().order_by(Client.created_at.desc()))
    return [_client_out(client, uploads, videos) for client, uploads, videos in rows]


@router.get("/{client_id}", response_model=ClientOut)
def get_client(client_id: uuid.UUID, session: SessionDep) -> ClientOut:
    row = session.execute(_clients_with_counts().where(Client.id == client_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return _client_out(*row)


@router.delete("/{client_id}", response_model=ClientDeletedOut)
def delete_client(client_id: uuid.UUID, session: SessionDep) -> ClientDeletedOut:
    """Erase a client and everything that belongs to it. Foreign-key cascades do the work."""
    client = _get_client(session, client_id)
    deleted = {
        "uploads": session.scalar(select(func.count()).select_from(Upload).where(Upload.client_id == client_id)),
        "videos": session.scalar(select(func.count()).select_from(Video).where(Video.client_id == client_id)),
        "metric_values": session.scalar(
            select(func.count()).select_from(VideoMetric).where(VideoMetric.client_id == client_id)
        ),
    }
    session.execute(delete(Client).where(Client.id == client.id))
    return ClientDeletedOut(deleted=deleted)


def _explicit_period(start: date | None, end: date | None, lifetime: bool) -> Period | None:
    """The period the operator stated on the upload form, or None if they did not state one."""
    if lifetime:
        if start or end:
            raise HTTPException(status_code=422, detail="period_lifetime cannot be combined with dates")
        return Period("lifetime", source="user")
    if start or end:
        if not (start and end):
            raise HTTPException(status_code=422, detail="period_start and period_end must be given together")
        if start > end:
            raise HTTPException(status_code=422, detail="period_start must not be after period_end")
        return Period("range", start, end, "user")
    return None


@router.post("/{client_id}/uploads", response_model=ImportOut)
def upload_export(
    client_id: uuid.UUID,
    file: UploadFile,
    session: SessionDep,
    response: Response,
    period_start: Annotated[date | None, Form()] = None,
    period_end: Annotated[date | None, Form()] = None,
    period_lifetime: Annotated[bool, Form()] = False,
    exported_on: Annotated[date | None, Form()] = None,
) -> ImportOut:
    """Import a Studio "Table data" export for a client.

    Importing the same file again changes nothing and answers 200 instead of 201. The date range is
    optional: if it is not stated it is read from the file name when present, else left unknown.
    """
    _get_client(session, client_id)
    explicit = _explicit_period(period_start, period_end, period_lifetime)
    spooled = spool_upload(file)
    try:
        result = import_export(
            session,
            client_id=client_id,
            path=spooled.path,
            filename=file.filename or "upload",
            sha256=spooled.sha256,
            period=explicit,
            exported_on=exported_on,
            max_rows=settings.max_rows,
        )
    except ImportRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    finally:
        os.unlink(spooled.path)

    response.status_code = 200 if result.duplicate else 201
    return ImportOut(
        upload_id=result.upload_id,
        duplicate=result.duplicate,
        videos=result.videos,
        metric_values=result.metric_values,
        total_values=result.total_values,
        period_kind=result.period.kind,
        period_start=result.period.start,
        period_end=result.period.end,
        period_source=result.period.source,
        new_unreviewed_metrics=result.new_unreviewed_metrics,
        warnings=result.warnings,
    )


@router.get("/{client_id}/uploads", response_model=list[UploadOut])
def list_uploads(client_id: uuid.UUID, session: SessionDep) -> list[Upload]:
    _get_client(session, client_id)
    query = select(Upload).where(Upload.client_id == client_id).order_by(Upload.imported_at.desc())
    return list(session.scalars(query))


@router.put("/{client_id}/uploads/{upload_id}/period", response_model=UploadOut)
def confirm_period(client_id: uuid.UUID, upload_id: int, body: PeriodIn, session: SessionDep) -> Upload:
    """Record the date range an upload covers, once the operator has confirmed it with the creator."""
    upload = session.scalar(select(Upload).where(Upload.id == upload_id, Upload.client_id == client_id))
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    upload.period_kind = body.kind
    upload.period_start = body.start
    upload.period_end = body.end
    upload.period_source = "user"
    session.flush()
    return upload
