"""Shared dependencies: service singletons, the in-memory dataset and request guards."""
from typing import Annotated, Any

from fastapi import Depends, HTTPException

from config import get_api_key
from services.analytics_service import (
    DataService,
    DescriptionService,
    DurationService,
    HeatmapService,
    KeywordService,
)
from services.researcher_service import ResearcherService

# The services hold no state, so one instance of each is enough.
data_svc = DataService()
heatmap_svc = HeatmapService()
keyword_svc = KeywordService()
duration_svc = DurationService()
description_svc = DescriptionService()
researcher_svc = ResearcherService()

# The last uploaded dataset, shared by every request. This is a stopgap that is replaced
# by per-client storage in the database phase.
dataset_cache: dict[str, Any] = {}


def get_dataset() -> dict[str, Any]:
    """Dependency: the loaded dataset, or a 404 telling the user to upload one."""
    if "dataset" not in dataset_cache:
        raise HTTPException(status_code=404, detail="No data loaded. Please upload a file.")
    return dataset_cache["dataset"]


def require_api_key() -> str:
    """Dependency: the configured YouTube API key, or a 400 pointing at Settings."""
    key = get_api_key()
    if not key:
        raise HTTPException(status_code=400, detail="YouTube API key not configured. Go to Settings.")
    return key


Dataset = Annotated[dict[str, Any], Depends(get_dataset)]
ApiKey = Annotated[str, Depends(require_api_key)]
