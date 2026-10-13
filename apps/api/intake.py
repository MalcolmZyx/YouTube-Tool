"""Receiving an uploaded file safely: size-limited copy to a temporary file, hashed as it streams."""
import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile

from config import settings

ALLOWED_SUFFIXES = {".xlsx", ".xlsm", ".csv"}
_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class SpooledFile:
    path: str
    sha256: str
    size: int
    suffix: str


def spool_upload(upload: UploadFile) -> SpooledFile:
    """Copy an upload to a temporary file, refusing unsupported types and oversized files.

    The caller owns the file and must delete `path` when done. The SHA-256 is computed while copying,
    so identifying a re-uploaded file costs no extra pass over the data.
    """
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload a .xlsx, .xlsm or .csv file.")

    digest = hashlib.sha256()
    written = 0
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := upload.file.read(_CHUNK_BYTES):
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413, detail=f"File too large. The maximum is {settings.max_upload_mb} MB."
                    )
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        os.unlink(path)
        raise
    return SpooledFile(path=path, sha256=digest.hexdigest(), size=written, suffix=suffix)
