"""Export upload and retrieval."""
import logging
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, UploadFile
from openpyxl.utils.exceptions import InvalidFileException

import deps
from config import get_api_key, settings
from schemas import DatasetOut
from services.analytics_service import ExportTooLargeError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])

_EXCEL_SUFFIXES = {".xlsx", ".xlsm"}
_ALLOWED_SUFFIXES = _EXCEL_SUFFIXES | {".csv"}
_CHUNK_BYTES = 1024 * 1024

# Errors that mean "this file is not a readable export" rather than "the server has a bug".
_UNREADABLE_FILE_ERRORS = (ValueError, KeyError, IndexError, zipfile.BadZipFile, InvalidFileException)


def _spool_to_disk(upload: UploadFile, suffix: str) -> str:
    """Copy the upload to a temporary file (pandas reads from a path), refusing oversized files."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    written = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := upload.file.read(_CHUNK_BYTES):
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413, detail=f"File too large. The maximum is {settings.max_upload_mb} MB."
                    )
                out.write(chunk)
    except BaseException:
        os.unlink(path)
        raise
    return path


@router.post("/dashboard/upload", response_model=DatasetOut)
def upload_file(file: UploadFile, num_rows: Annotated[str | None, Form()] = None) -> dict:
    """Read a Studio export (.xlsx, .xlsm or .csv), enrich it from the YouTube API and cache it.

    Form fields:
      - file: the spreadsheet
      - num_rows (optional): only process the first N videos
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload a .xlsx, .xlsm or .csv file.")

    limit = int(num_rows) if num_rows and num_rows.isdigit() else None
    tmp_path = _spool_to_disk(file, suffix)

    try:
        result = deps.data_svc.load_file(
            tmp_path, api_key=get_api_key(), num_rows=limit, max_rows=settings.max_rows
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
        os.unlink(tmp_path)

    deps.dataset_cache["dataset"] = result
    return result  # `metadata` is dropped by the response model


@router.get("/dashboard", response_model=DatasetOut)
def get_dashboard(dataset: deps.Dataset) -> dict:
    """The currently loaded dataset."""
    return dataset
