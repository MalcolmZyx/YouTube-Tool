"""A client's stored export, served to the dashboard and the analyses (the database-backed twin of /api/dashboard)."""
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

import deps
from routers.analysis import make_router
from routers.clients import SessionDep, _get_client
from schemas import DatasetOut, EnrichOut
from services.client_data import NoUpload, load_table, pick_upload
from youtube.client import QuotaExceeded, YouTubeError
from youtube.store import load_public_data, refresh_client


def get_client_dataset(client_id: uuid.UUID, session: SessionDep, upload_id: int | None = None) -> dict[str, Any]:
    """Dependency: the client's dataset from the database. `upload_id` picks an upload; default is the latest."""
    _get_client(session, client_id)
    try:
        upload = pick_upload(session, client_id, upload_id)
    except NoUpload as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    frame, total_row = load_table(session, upload)
    dataset = deps.data_svc.build_dataset(frame, total_row)
    _attach_public_data(dataset, load_public_data(session, client_id))
    return dataset


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
        result = refresh_client(session, client_id, api_key, force=force)
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from None
    except YouTubeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return EnrichOut(requested=result.requested, stored=result.stored, unavailable=result.unavailable)
