"""
YouTube Researcher Service
Refactored from YTRTool.ipynb
Handles search, autocomplete ideas, and competitor tag analysis.
"""
import json
import math
import re
from collections import defaultdict

import requests
from googleapiclient.discovery import build


class ResearcherService:
    """
    Search YouTube for videos, return structured data, and analyse tags.
    """

    STOP_WORDS = {
        "video", "videos", "youtube", "shorts", "#shorts", "#short", "short",
        "tiktok", "youtuber", "news", "trending",
    }
    SYNONYMS = {"mr beast": "mrbeast", "mr. beast": "mrbeast"}

    # ── Search ─────────────────────────────────────────────────────────────

    def search(
        self,
        api_key: str,
        query: str,
        max_results: int = 20,
        order: str = "relevance",
        published_after: str | None = None,
        published_before: str | None = None,
        video_duration: str = "any",
    ) -> list[dict]:
        """
        Search YouTube for videos matching *query* and return enriched rows.
        """
        if not api_key:
            raise ValueError("API key is required.")

        youtube = build("youtube", "v3", developerKey=api_key)

        search_req = youtube.search().list(
            q=query,
            part="snippet",
            maxResults=max_results,
            type="video",
            order=order,
            publishedAfter=published_after,
            publishedBefore=published_before,
            videoDuration=video_duration,
        )
        search_resp = search_req.execute()
        video_ids = [item["id"]["videoId"] for item in search_resp.get("items", [])]
        if not video_ids:
            return []

        video_req = youtube.videos().list(
            part="snippet,statistics",
            id=",".join(video_ids),
        )
        video_resp = video_req.execute()

        rows = []
        for item in video_resp.get("items", []):
            snippet = item["snippet"]
            stats = item.get("statistics", {})
            thumbs = snippet.get("thumbnails", {})
            thumb = (
                thumbs.get("high", {}).get("url")
                or thumbs.get("medium", {}).get("url")
                or thumbs.get("default", {}).get("url")
                or ""
            )
            rows.append({
                "video_id": item["id"],
                "title": snippet.get("title", ""),
                "url": f"https://www.youtube.com/watch?v={item['id']}",
                "channel": snippet.get("channelTitle", ""),
                "published_at": snippet.get("publishedAt", ""),
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
                "tags": snippet.get("tags", []),
                "thumbnail": thumb,
                "description": snippet.get("description", ""),
            })

        if order == "viewCount":
            rows.sort(key=lambda r: r["views"], reverse=True)

        return rows

    # ── Video ideas via autocomplete ───────────────────────────────────────

    def get_ideas(self, topic: str) -> list[str]:
        """
        Hit YouTube's (unofficial) autocomplete endpoint to surface
        related queries for *topic*.
        """
        if not topic:
            return []
        # Passing the topic via `params` URL-encodes it. Formatting it into the URL string would let
        # a topic like "x&client=other" inject extra query parameters.
        url = "https://suggestqueries.google.com/complete/search"
        try:
            r = requests.get(url, params={"client": "youtube", "q": topic}, timeout=8)
            r.raise_for_status()
            text = r.text
            match = re.search(r"\((.*)\)", text)
            if not match:
                return []
            data = json.loads(match.group(1))
            return [item[0] for item in data[1]]
        except Exception:
            return []

    # ── Tag analysis ───────────────────────────────────────────────────────

    def analyze_tags(self, rows: list[dict], top_n: int = 20) -> list[dict]:
        """
        View-weighted scoring of whole tag phrases across search results.
        """
        scores: dict[str, float] = defaultdict(float)
        for row in rows:
            views = max(row.get("views", 1), 1)
            weight = math.log10(views + 1)
            tags = row.get("tags", [])
            if not isinstance(tags, list):
                continue
            seen = set()
            for tag in tags:
                t = self.SYNONYMS.get(tag.lower(), tag.lower())
                if t and t not in self.STOP_WORDS:
                    seen.add(t)
            for t in seen:
                scores[t] += weight

        sorted_tags = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [{"tag": t, "score": round(s, 2)} for t, s in sorted_tags[:top_n]]
