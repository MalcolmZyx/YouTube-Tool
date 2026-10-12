"""API key settings and the health check."""
import os

from fastapi import APIRouter, HTTPException

import deps
from config import get_api_key
from schemas import HealthOut, SaveSettingsIn, SaveSettingsOut, SettingsOut

router = APIRouter(tags=["system"])


@router.get("/settings", response_model=SettingsOut)
def get_settings() -> SettingsOut:
    """Whether an API key is configured, with a masked preview."""
    key = get_api_key()
    preview = f"{'*' * 8}{key[-4:]}" if len(key) > 4 else ""
    return SettingsOut(has_api_key=bool(key), key_preview=preview)


@router.post("/settings", response_model=SaveSettingsOut)
def save_settings(body: SaveSettingsIn) -> SaveSettingsOut:
    """Set the API key for the running process. It is not written to disk."""
    key = body.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="api_key is required")
    os.environ["YOUTUBE_API_KEY"] = key
    return SaveSettingsOut(ok=True, message="API key saved for this session.")


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(status="ok", cache_loaded="dataset" in deps.dataset_cache)
