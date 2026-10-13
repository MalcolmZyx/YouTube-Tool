"""Export upload and retrieval for the single in-memory dataset.

This is the original, pre-database flow. Clients and persistent imports live in routers/clients.py;
this route stays until the frontend moves over to them.
"""
import logging
import os
import zipfile
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, UploadFile
from openpyxl.utils.exceptions import InvalidFileException

import deps
from config import get_api_key, settings
from intake import spool_upload
from schemas import DatasetOut
from services.analytics_service import ExportTooLargeError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])

# Errors that mean "this file is not a readable export" rather than "the server has a bug".
_UNREADABLE_FILE_ERRORS = (ValueError, KeyError, IndexError, zipfile.BadZipFile, InvalidFileException)


@router.post("/dashboard/upload", response_model=DatasetOut)
def upload_file(file: UploadFile, num_rows: Annotated[str | None, Form()] = None) -> dict:
    """Read a Studio export (.xlsx, .xlsm or .csv), enrich it from the YouTube API and cache it.

    Form fields:
      - file: the spreadsheet
      - num_rows (optional): only process the first N videos
    """
    spooled = spool_upload(file)
    limit = int(num_rows) if num_rows and num_rows.isdigit() else None

    try:
        result = deps.data_svc.load_file(
            spooled.path, api_key=get_api_key(), num_rows=limit, max_rows=settings.max_rows
        )
    except ExportTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except _UNREADABLE_FILE_ERRORS:
        logger.warning("Could not read uploaded file %r", file.filename, exc_info=True)
        raise HTTPException(
            status_code=422,
            detail="Could not read this file. Make sure it is a YouTube Studio export (.xlsx, .xlsm or .csv).",
        ) from None
    finally:
        os.unlink(spooled.path)

    deps.dataset_cache["dataset"] = result
    return result  # `metadata` is dropped by the response model


@router.get("/dashboard", response_model=DatasetOut)
def get_dashboard(dataset: deps.Dataset) -> dict:
    """The currently loaded dataset."""
    return dataset
