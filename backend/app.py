"""
app.py  –  Flask REST API
YouTube Analytics & Research Tool
"""
import os
import tempfile

import pandas as pd
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

# ── local imports ─────────────────────────────────────────────────────────
import sys
sys.path.insert(0, os.path.dirname(__file__))
from services.analytics_service import (
    DataService, HeatmapService, KeywordService,
    DurationService, DescriptionService,
)
from services.researcher_service import ResearcherService

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ── singletons ────────────────────────────────────────────────────────────
data_svc        = DataService()
heatmap_svc     = HeatmapService()
keyword_svc     = KeywordService()
duration_svc    = DurationService()
description_svc = DescriptionService()
researcher_svc  = ResearcherService()

# ── session cache (in-memory, per-process) ────────────────────────────────
_cache: dict = {}   # stores the last loaded dataset


# ═══════════════════════════════════════════════════════════════════════════
# Settings / API Key
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/settings", methods=["GET"])
def get_settings():
    """Return whether an API key is configured."""
    key = os.environ.get("YOUTUBE_API_KEY", "")
    return jsonify({"has_api_key": bool(key), "key_preview": f"{'*' * 8}{key[-4:]}" if len(key) > 4 else ""})


@app.route("/api/settings", methods=["POST"])
def save_settings():
    """Accept an API key at runtime (stored only in process env)."""
    body = request.get_json(force=True) or {}
    key = body.get("api_key", "").strip()
    if not key:
        return jsonify({"error": "api_key is required"}), 400
    os.environ["YOUTUBE_API_KEY"] = key
    return jsonify({"ok": True, "message": "API key saved for this session."})


# ═══════════════════════════════════════════════════════════════════════════
# Dashboard – data upload + retrieval
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/dashboard/upload", methods=["POST"])
def upload_file():
    """
    Accepts an Excel / CSV upload, runs data preparation and YouTube enrichment,
    and caches the result.
    
    Form fields:
      - file  : the spreadsheet
      - num_rows (optional): limit rows processed
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    num_rows = request.form.get("num_rows")
    num_rows = int(num_rows) if num_rows and str(num_rows).isdigit() else None

    api_key = os.environ.get("YOUTUBE_API_KEY", "")

    suffix = ".xlsx" if f.filename.endswith((".xlsx", ".xlsm")) else ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        f.save(tmp.name)
        tmp_path = tmp.name

    try:
        result = data_svc.load_file(tmp_path, api_key=api_key, num_rows=num_rows)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    finally:
        os.unlink(tmp_path)

    _cache["dataset"] = result
    return jsonify({k: v for k, v in result.items() if k != "metadata"})


@app.route("/api/dashboard", methods=["GET"])
def get_dashboard():
    """Return the currently cached dataset (without raw metadata)."""
    if "dataset" not in _cache:
        return jsonify({"error": "No data loaded. Please upload a file."}), 404
    ds = _cache["dataset"]
    return jsonify({k: v for k, v in ds.items() if k != "metadata"})


# ═══════════════════════════════════════════════════════════════════════════
# Heatmap
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/heatmap", methods=["GET"])
def get_heatmap():
    """
    Compute calendar + day-of-week performance data.
    Query params:
      - metric : column name (default 'Views')
    """
    if "dataset" not in _cache:
        return jsonify({"error": "No data loaded."}), 404

    metric = request.args.get("metric", "Views")
    ds = _cache["dataset"]
    rows = ds["rows"]
    df = pd.DataFrame(rows)

    result = heatmap_svc.compute(df, metric_col=metric)
    result["available_metrics"] = ds.get("numeric_columns", []) + ds.get("percent_columns", [])
    return jsonify(result)


# ═══════════════════════════════════════════════════════════════════════════
# Keyword / Tag Analysis
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/keywords/weighted", methods=["GET"])
def keywords_weighted():
    """
    View-weighted tag scoring over the cached dataset metadata.
    Query params:
      - top_n : number of tags to return (default 25)
    """
    if "dataset" not in _cache:
        return jsonify({"error": "No data loaded."}), 404

    top_n = int(request.args.get("top_n", 25))
    metadata = _cache["dataset"].get("metadata", [])
    rows = _cache["dataset"]["rows"]
    video_id_col = _cache["dataset"]["video_id_col"]

    # Build a DataFrame that keyword_svc expects
    meta_df = pd.DataFrame(metadata) if metadata else pd.DataFrame(columns=["video_id", "tags"])

    # Attach views from the main rows
    rows_df = pd.DataFrame(rows)
    if not meta_df.empty and video_id_col in rows_df.columns:
        rows_df[video_id_col] = rows_df[video_id_col].astype(str).str.strip()
        meta_df["video_id"] = meta_df["video_id"].astype(str).str.strip()
        merged = meta_df.merge(rows_df[[video_id_col, "Views"]], left_on="video_id", right_on=video_id_col, how="left")
        merged.rename(columns={"Views": "views"}, inplace=True)
        merged["Tags"] = merged["tags"]
        result = keyword_svc.weighted_tags(merged.rename(columns={"views": "Views"}), top_n=top_n)
    else:
        result = []

    return jsonify({"tags": result})


@app.route("/api/keywords/top-vs-bottom", methods=["GET"])
def keywords_top_vs_bottom():
    """
    Compare top 20% vs bottom 20% of videos by views.
    Query params:
      - top_n  (default 20)
      - views_col (default 'Views')
    """
    if "dataset" not in _cache:
        return jsonify({"error": "No data loaded."}), 404

    top_n = int(request.args.get("top_n", 20))
    views_col = request.args.get("views_col", "Views")
    ds = _cache["dataset"]
    df = pd.DataFrame(ds["rows"])
    metadata = ds.get("metadata", [])

    result = keyword_svc.top_vs_bottom(df, metadata, views_col=views_col, top_n=top_n)
    return jsonify(result)


# ═══════════════════════════════════════════════════════════════════════════
# Duration Analysis
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/duration", methods=["GET"])
def duration_analysis():
    """
    Bucket videos by Duration and compute stats per bucket.
    Query params:
      - metric : column to aggregate (default 'Views')
    """
    if "dataset" not in _cache:
        return jsonify({"error": "No data loaded."}), 404

    metric = request.args.get("metric", "Views")
    df = pd.DataFrame(_cache["dataset"]["rows"])
    result = duration_svc.analyze(df, metric_col=metric)
    return jsonify(result)


# ═══════════════════════════════════════════════════════════════════════════
# Description Analysis
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/descriptions", methods=["GET"])
def descriptions():
    """Return per-video description data."""
    if "dataset" not in _cache:
        return jsonify({"error": "No data loaded."}), 404

    ds = _cache["dataset"]
    result = description_svc.analyze(ds["rows"], ds["video_id_col"])
    return jsonify({"videos": result, "total": len(result)})


# ═══════════════════════════════════════════════════════════════════════════
# YouTube Researcher Tool (YTRTool.ipynb)
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/researcher/search", methods=["POST"])
def researcher_search():
    """
    Search YouTube and return enriched video rows + tag analysis.

    JSON body:
      query           : str  (required)
      max_results     : int  (default 20)
      order           : relevance | viewCount | date | rating
      published_after : ISO date string  (optional)
      published_before: ISO date string  (optional)
      video_duration  : any | short | medium | long
    """
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        return jsonify({"error": "YouTube API key not configured. Go to Settings."}), 400

    body = request.get_json(force=True) or {}
    query = body.get("query", "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400

    try:
        rows = researcher_svc.search(
            api_key=api_key,
            query=query,
            max_results=int(body.get("max_results", 20)),
            order=body.get("order", "relevance"),
            published_after=body.get("published_after"),
            published_before=body.get("published_before"),
            video_duration=body.get("video_duration", "any"),
        )
        tags = researcher_svc.analyze_tags(rows, top_n=int(body.get("top_n", 20)))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"videos": rows, "tags": tags, "total": len(rows)})


@app.route("/api/researcher/ideas", methods=["GET"])
def researcher_ideas():
    """
    Return YouTube autocomplete suggestions for a topic.
    Query params:
      - topic : str (required)
    """
    topic = request.args.get("topic", "").strip()
    if not topic:
        return jsonify({"error": "topic is required"}), 400

    ideas = researcher_svc.get_ideas(topic)
    return jsonify({"ideas": ideas, "topic": topic})


# ═══════════════════════════════════════════════════════════════════════════
# Health check
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "cache_loaded": "dataset" in _cache})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
