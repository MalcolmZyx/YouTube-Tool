"""YouTube search research: results with tag analysis, and autocomplete ideas."""
import logging

from fastapi import APIRouter, HTTPException
from googleapiclient.errors import HttpError

import deps
from schemas import IdeasOut, SearchIn, SearchOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/researcher", tags=["researcher"])


@router.post("/search", response_model=SearchOut)
def researcher_search(body: SearchIn, api_key: deps.ApiKey) -> dict:
    """Search YouTube and return enriched videos plus a view-weighted tag analysis."""
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    try:
        rows = deps.researcher_svc.search(
            api_key=api_key,
            query=query,
            max_results=body.max_results,
            order=body.order,
            published_after=body.published_after,
            published_before=body.published_before,
            video_duration=body.video_duration,
        )
    except HttpError as exc:
        # str(exc) contains the request URL, which includes the API key, so it must never be
        # forwarded to the browser. `exc.reason` is just Google's own message.
        status = getattr(exc.resp, "status", 502)
        logger.warning("YouTube API error %s: %s", status, exc.reason)
        if status == 403 and "quota" in str(exc.reason).lower():
            raise HTTPException(
                status_code=429, detail="YouTube API quota exceeded. Try again after it resets."
            ) from None
        raise HTTPException(status_code=502, detail=f"YouTube API error: {exc.reason}") from None

    tags = deps.researcher_svc.analyze_tags(rows, top_n=body.top_n)
    return {"videos": rows, "tags": tags, "total": len(rows)}


@router.get("/ideas", response_model=IdeasOut)
def researcher_ideas(topic: str = "") -> dict:
    """YouTube autocomplete suggestions for a topic."""
    topic = topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="topic is required")
    return {"ideas": deps.researcher_svc.get_ideas(topic), "topic": topic}
