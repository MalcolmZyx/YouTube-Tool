"""
Analytics Service
Refactored from youtubeAnaTest10.ipynb
Handles data ingestion, enrichment, and metric calculations.
"""
import json
import math
import re
from collections import defaultdict

import numpy as np
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def convert_seconds_to_min_sec(seconds):
    """301 -> '5:01'"""
    try:
        seconds = int(float(seconds))
    except (ValueError, TypeError):
        return str(seconds)
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


# ---------------------------------------------------------------------------
# YouTube API helpers
# ---------------------------------------------------------------------------

def get_video_info(video_id: str, api_key: str) -> dict | None:
    """
    Fetch snippet (description, tags, categoryId, thumbnail) for one video.
    Returns None on failure.
    """
    if not api_key or not video_id or len(str(video_id).strip()) != 11:
        return None
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {"part": "snippet", "id": video_id.strip(), "key": api_key}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if not data.get("items"):
            return None
        snippet = data["items"][0]["snippet"]
        thumbs = snippet.get("thumbnails", {})
        thumb_url = (
            thumbs.get("maxres", {}).get("url")
            or thumbs.get("standard", {}).get("url")
            or thumbs.get("high", {}).get("url")
            or thumbs.get("medium", {}).get("url")
            or thumbs.get("default", {}).get("url")
        )
        return {
            "description": snippet.get("description", ""),
            "tags": snippet.get("tags", []),
            "category_id": snippet.get("categoryId"),
            "thumbnail_url": thumb_url,
            "title": snippet.get("title", ""),
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Data ingestion & preparation
# ---------------------------------------------------------------------------

class DataService:
    """
    Responsible for loading an Excel/CSV file, classifying columns,
    and enriching rows with YouTube metadata.
    """

    # columns that are never shown in the main table
    _HIDDEN = {"thumbnail_url", "video_description", "video_title", "Video publish time"}

    def load_file(self, file_path: str, api_key: str = "", num_rows: int | None = None) -> dict:
        """
        Load a spreadsheet and return a JSON-serialisable dict ready for the frontend.
        """
        if file_path.endswith((".xlsx", ".xlsm")):
            df = pd.read_excel(file_path, engine="openpyxl")
        else:
            df = pd.read_csv(file_path)

        # ── Save and strip the "Total" footer row ──────────────────────────
        total_row = None
        mask = df.iloc[:, 0].astype(str).str.strip().str.lower() == "total"
        if mask.any():
            total_row = df.loc[mask.idxmax()].copy()
            df = df.drop(index=mask.idxmax()).reset_index(drop=True)

        if num_rows:
            df = df.head(num_rows)

        df = df.dropna(how="all").dropna(axis=1, how="all").fillna("")

        # ── Detect the video-ID column ──────────────────────────────────────
        video_id_col = df.columns[0]

        # ── Parse publish time ──────────────────────────────────────────────
        if "Video publish time" in df.columns:
            df["Video publish time"] = pd.to_datetime(df["Video publish time"], errors="coerce")

        # ── Duration formatting ─────────────────────────────────────────────
        if "Duration" in df.columns and pd.api.types.is_numeric_dtype(df["Duration"]):
            dur_idx = df.columns.get_loc("Duration")
            df.insert(dur_idx + 1, "Duration (mins)", df["Duration"].apply(convert_seconds_to_min_sec))

        # ── Classify columns ────────────────────────────────────────────────
        text_cols, numeric_cols, percent_cols = self._classify_columns(df, video_id_col)

        # ── Drop all-zero numeric/percent columns ───────────────────────────
        zero_cols = [
            c for c in numeric_cols + percent_cols
            if pd.to_numeric(df[c], errors="coerce").fillna(0).sum() == 0
        ]
        df.drop(columns=zero_cols, inplace=True, errors="ignore")
        numeric_cols = [c for c in numeric_cols if c not in zero_cols]
        percent_cols = [c for c in percent_cols if c not in zero_cols]
        if total_row is not None:
            total_row = total_row.drop(labels=zero_cols, errors="ignore").reindex(df.columns).fillna("")

        # ── Compute column-wise share percentages ───────────────────────────
        shares: dict[str, dict] = {}
        for col in numeric_cols:
            numeric_series = pd.to_numeric(df[col], errors="coerce").fillna(0)
            col_sum = numeric_series.sum()
            if col_sum > 0:
                shares[col] = (numeric_series / col_sum * 100).round(1).to_dict()
            else:
                shares[col] = {i: 0.0 for i in df.index}

        # ── Fetch YouTube metadata ──────────────────────────────────────────
        metadata_rows = []
        for idx, row in df.iterrows():
            vid = str(row[video_id_col]).strip()
            if len(vid) == 11 and api_key:
                info = get_video_info(vid, api_key)
                if info:
                    df.at[idx, "thumbnail_url"] = info["thumbnail_url"]
                    df.at[idx, "video_description"] = info["description"]
                    df.at[idx, "video_title"] = info["title"]
                    metadata_rows.append({"video_id": vid, "tags": info["tags"], "category_id": info["category_id"]})
                else:
                    df.at[idx, "thumbnail_url"] = ""
                    df.at[idx, "video_description"] = ""
                    df.at[idx, "video_title"] = ""
            else:
                df.at[idx, "thumbnail_url"] = ""
                df.at[idx, "video_description"] = ""
                df.at[idx, "video_title"] = ""

        # ── Serialise ───────────────────────────────────────────────────────
        rows = self._serialise_rows(df, video_id_col)

        total_row_json = None
        if total_row is not None:
            total_row_json = {k: (str(v) if not isinstance(v, (int, float)) else v)
                              for k, v in total_row.to_dict().items()}

        # columns to render in the table
        display_cols = [c for c in df.columns if c not in self._HIDDEN]

        return {
            "rows": rows,
            "total_row": total_row_json,
            "columns": display_cols,
            "text_columns": text_cols,
            "numeric_columns": numeric_cols,
            "percent_columns": percent_cols,
            "shares": shares,
            "video_id_col": video_id_col,
            "metadata": metadata_rows,
        }

    # ── private helpers ────────────────────────────────────────────────────

    def _classify_columns(self, df: pd.DataFrame, video_id_col: str):
        text_cols, numeric_cols, percent_cols = [], [], []
        for col in df.columns:
            if col in self._HIDDEN or col == "Video publish time":
                continue
            if col == video_id_col or col == "Duration (mins)":
                text_cols.append(col)
                continue
            if df[col].astype(str).str.strip().eq("").all():
                continue

            pct_keyword = any(k in col.lower() for k in ["%", "rate", "percentage", "ctr"])
            pct_values = df[col].astype(str).str.contains("%", na=False).any()

            if pct_keyword or pct_values:
                percent_cols.append(col)
                df[col] = (
                    pd.to_numeric(df[col].astype(str).str.replace("%", "", regex=False), errors="coerce").fillna(0)
                )
            elif pd.api.types.is_numeric_dtype(df[col]):
                numeric_cols.append(col)
            else:
                test = pd.to_numeric(df[col], errors="coerce")
                if test.notna().any():
                    numeric_cols.append(col)
                    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
                else:
                    text_cols.append(col)

        return text_cols, numeric_cols, percent_cols

    def _serialise_rows(self, df: pd.DataFrame, video_id_col: str) -> list[dict]:
        rows = []
        for _, row in df.iterrows():
            r: dict = {}
            for col in df.columns:
                val = row[col]
                if isinstance(val, pd.Timestamp):
                    r[col] = val.isoformat() if not pd.isna(val) else None
                elif isinstance(val, float) and math.isnan(val):
                    r[col] = None
                else:
                    r[col] = val if not isinstance(val, (np.integer, np.floating)) else val.item()
            rows.append(r)
        return rows


# ---------------------------------------------------------------------------
# Calendar / heatmap service
# ---------------------------------------------------------------------------

class HeatmapService:
    def compute(self, df: pd.DataFrame, date_col: str = "Video publish time", metric_col: str = "Views") -> dict:
        df = df.copy()
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col])
        if df.empty:
            return {"calendar": [], "day_of_week": []}

        df["date_str"] = df[date_col].dt.strftime("%Y-%m-%d")
        df["dow"] = df[date_col].dt.dayofweek   # 0=Mon
        df["dow_name"] = df[date_col].dt.strftime("%A")

        # daily aggregation
        if metric_col and metric_col in df.columns:
            df[metric_col] = pd.to_numeric(df[metric_col], errors="coerce").fillna(0)
            daily = df.groupby("date_str")[metric_col].sum().reset_index()
            daily.columns = ["date", "value"]
        else:
            daily = df["date_str"].value_counts().reset_index()
            daily.columns = ["date", "value"]

        # day-of-week stats
        if metric_col and metric_col in df.columns:
            dow = (
                df.groupby(["dow", "dow_name"])[metric_col]
                .agg(total="sum", avg="mean", count="count")
                .reset_index()
                .sort_values("dow")
            )
        else:
            dow = (
                df.groupby(["dow", "dow_name"])
                .size()
                .reset_index(name="count")
            )
            dow["total"] = dow["count"]
            dow["avg"] = 1.0

        return {
            "calendar": daily.to_dict(orient="records"),
            "day_of_week": dow.rename(columns={"dow_name": "day"}).to_dict(orient="records"),
            "metric": metric_col,
        }


# ---------------------------------------------------------------------------
# Keyword analysis service
# ---------------------------------------------------------------------------

class KeywordService:
    """
    View-weighted tag scoring (YTRTool.ipynb logic) plus top-vs-bottom
    cluster analysis (youtubeAnaTest10.ipynb logic, simplified).
    """

    STOP_WORDS = {"video", "videos", "youtube", "shorts", "#shorts", "#short", "short",
                  "tiktok", "youtuber", "news", "trending"}
    SYNONYMS = {"mr beast": "mrbeast", "mr. beast": "mrbeast"}

    def weighted_tags(self, df: pd.DataFrame, top_n: int = 20) -> list[dict]:
        """
        Score each unique tag phrase by log10(views) * occurrence across videos.
        Returns top_n tags sorted by score descending.
        """
        tag_scores: dict[str, float] = defaultdict(float)

        for _, row in df.iterrows():
            views = max(float(row.get("Views") or row.get("views") or 1), 1)
            tags = row.get("Tags") or row.get("tags") or []
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = [t.strip() for t in tags.split(",") if t.strip()]
            if not isinstance(tags, list):
                continue

            weight = math.log10(views + 1)
            seen = set()
            for tag in tags:
                t = self.SYNONYMS.get(tag.lower(), tag.lower())
                if t not in self.STOP_WORDS:
                    seen.add(t)
            for t in seen:
                tag_scores[t] += weight

        sorted_tags = sorted(tag_scores.items(), key=lambda x: x[1], reverse=True)
        return [{"tag": t, "score": round(s, 2)} for t, s in sorted_tags[:top_n]]

    def top_vs_bottom(self, df: pd.DataFrame, metadata: list[dict],
                      views_col: str = "Views", top_n: int = 20) -> dict:
        """
        Compare tags of top N% vs bottom N% videos by views.
        Returns two ranked tag lists.
        """
        df = df.copy()
        df[views_col] = pd.to_numeric(df[views_col], errors="coerce").fillna(0)
        id_col = df.columns[0]
        df[id_col] = df[id_col].astype(str).str.strip()

        meta_map: dict[str, list] = {
            str(m["video_id"]).strip(): (m.get("tags") or []) for m in metadata
        }

        sorted_ids = df.sort_values(views_col, ascending=False)[id_col].tolist()
        n = len(sorted_ids)
        cutoff = max(int(n * 0.20), 1)
        top_ids = set(sorted_ids[:cutoff])
        bottom_ids = set(sorted_ids[max(n - cutoff, cutoff):])

        def tag_scores_for(ids):
            scores: dict[str, float] = defaultdict(float)
            for vid in ids:
                views = float(df.loc[df[id_col] == vid, views_col].sum() or 1)
                w = math.log10(views + 1)
                tags = meta_map.get(vid, [])
                if isinstance(tags, str):
                    try:
                        tags = json.loads(tags)
                    except Exception:
                        tags = [t.strip() for t in tags.split(",") if t.strip()]
                for tag in tags:
                    t = tag.lower().strip()
                    if t and t not in self.STOP_WORDS:
                        scores[t] += w
            return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]

        top_tags = [{"tag": t, "score": round(s, 2)} for t, s in tag_scores_for(top_ids)]
        bottom_tags = [{"tag": t, "score": round(s, 2)} for t, s in tag_scores_for(bottom_ids)]

        return {"top": top_tags, "bottom": bottom_tags}


# ---------------------------------------------------------------------------
# Duration analysis service
# ---------------------------------------------------------------------------

class DurationService:
    BUCKETS = [
        (0, 8, "0-7s"), (8, 16, "8-15s"), (16, 31, "16-30s"),
        (31, 60, "31-59s"), (60, 240, "1-4m"), (240, 540, "4-9m"),
        (540, 900, "9-15m"),
    ]

    def analyze(self, df: pd.DataFrame, metric_col: str = "Views") -> dict:
        df = df.copy()
        if "Duration" not in df.columns or metric_col not in df.columns:
            return {"buckets": []}

        df["Duration"] = pd.to_numeric(df["Duration"], errors="coerce")
        df[metric_col] = pd.to_numeric(df[metric_col], errors="coerce")
        df = df.dropna(subset=["Duration"])

        max_d = float(df["Duration"].max())
        edges = list(self.BUCKETS)
        last = 900
        while last < max_d:
            nxt = last + 300
            lbl = f"{last // 60}-{nxt // 60}m"
            edges.append((last, nxt, lbl))
            last = nxt
        edges.append((last, float("inf"), f"{last // 60}m+"))

        result = []
        for lo, hi, label in edges:
            mask = (df["Duration"] >= lo) & (df["Duration"] < hi)
            sub = df.loc[mask, metric_col].dropna()
            if sub.empty:
                continue
            result.append({
                "bucket": label,
                "count": int(mask.sum()),
                "mean": round(float(sub.mean()), 1),
                "median": round(float(sub.median()), 1),
                "total": round(float(sub.sum()), 0),
            })

        return {"buckets": result, "metric": metric_col}


# ---------------------------------------------------------------------------
# Description analysis service
# ---------------------------------------------------------------------------

class DescriptionService:
    def analyze(self, rows: list[dict], video_id_col: str) -> list[dict]:
        """
        Return per-video description data for the Description table.
        """
        out = []
        for row in rows:
            desc = row.get("video_description") or ""
            if not desc or desc.startswith(("Failed", "Invalid", "N/A")):
                continue
            vid = str(row.get(video_id_col, "")).strip()
            title = row.get("video_title") or row.get("Video title") or row.get("Title") or vid
            out.append({
                "video_id": vid,
                "title": title,
                "description": desc,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "thumbnail_url": row.get("thumbnail_url") or "",
                "char_count": len(desc),
                "line_count": desc.count("\n") + 1,
                "has_links": bool(re.search(r"http", desc)),
                "has_hashtags": bool(re.search(r"#\w+", desc)),
                "has_timestamps": bool(re.search(r"\d+:\d+", desc)),
            })
        return out
