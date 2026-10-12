"""Export upload and retrieval."""
import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, UploadFile
from openpyxl.utils.exceptions import InvalidFileException

import deps
from config import get_api_key
from schemas import DatasetOut

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])

_EXCEL_SUFFIXES = {".xlsx", ".xlsm"}
_ALLOWED_SUFFIXES = _EXCEL_SUFFIXES | {".csv"}

# Errors that mean "this file is not a readable export" rather than "the server has a bug".
_UNREADABLE_FILE_ERRORS = (ValueError, KeyError, IndexError, zipfile.BadZipFile, InvalidFileException)


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

    # pandas reads from a path, so the upload is spooled to a temporary file first.
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        result = deps.data_svc.load_file(tmp_path, api_key=get_api_key(), num_rows=limit)
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
