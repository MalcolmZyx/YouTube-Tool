"""A client's stored export, served to the dashboard and the analyses (the database-backed twin of /api/dashboard)."""
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

import deps
from routers.analysis import make_router
from routers.clients import SessionDep, _get_client
from schemas import DatasetOut
from services.client_data import NoUpload, load_table, pick_upload


def get_client_dataset(client_id: uuid.UUID, session: SessionDep, upload_id: int | None = None) -> dict[str, Any]:
    """Dependency: the client's dataset from the database. `upload_id` picks an upload; default is the latest."""
    _get_client(session, client_id)
    try:
        upload = pick_upload(session, client_id, upload_id)
    except NoUpload as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    frame, total_row = load_table(session, upload)
    return deps.data_svc.build_dataset(frame, total_row)


router = APIRouter(prefix="/clients/{client_id}")
router.include_router(make_router(get_client_dataset))


@router.get("/dashboard", response_model=DatasetOut, tags=["clients"])
def client_dashboard(dataset: Annotated[dict[str, Any], Depends(get_client_dataset)]) -> dict:
    """The client's table: videos, the Total row and the columns the UI should show."""
    return dataset
