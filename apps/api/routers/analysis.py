"""Analyses over the loaded dataset: heatmap, keywords, duration and descriptions."""
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Query

import deps
from schemas import DescriptionsOut, DurationOut, HeatmapOut, TopVsBottomOut, WeightedTagsOut

router = APIRouter(tags=["analysis"])


@router.get("/heatmap", response_model=HeatmapOut, response_model_exclude_unset=True)
def get_heatmap(dataset: deps.Dataset, metric: str = "Views") -> dict:
    """Calendar and day-of-week performance for one metric column."""
    df = pd.DataFrame(dataset["rows"])
    result = deps.heatmap_svc.compute(df, metric_col=metric)
    result["available_metrics"] = dataset.get("numeric_columns", []) + dataset.get("percent_columns", [])
    return result


@router.get("/keywords/weighted", response_model=WeightedTagsOut)
def keywords_weighted(dataset: deps.Dataset, top_n: Annotated[int, Query(ge=1, le=200)] = 25) -> dict:
    """Tags scored by the views of the videos that use them."""
    metadata = dataset.get("metadata", [])
    video_id_col = dataset["video_id_col"]
    rows_df = pd.DataFrame(dataset["rows"])

    if not metadata or video_id_col not in rows_df.columns:
        return {"tags": []}

    meta_df = pd.DataFrame(metadata)
    rows_df[video_id_col] = rows_df[video_id_col].astype(str).str.strip()
    meta_df["video_id"] = meta_df["video_id"].astype(str).str.strip()
    merged = meta_df.merge(rows_df[[video_id_col, "Views"]], left_on="video_id", right_on=video_id_col, how="left")
    merged["Tags"] = merged["tags"]
    return {"tags": deps.keyword_svc.weighted_tags(merged, top_n=top_n)}


@router.get("/keywords/top-vs-bottom", response_model=TopVsBottomOut)
def keywords_top_vs_bottom(
    dataset: deps.Dataset,
    top_n: Annotated[int, Query(ge=1, le=200)] = 20,
    views_col: str = "Views",
) -> dict:
    """Tags of the top fifth of videos compared with the bottom fifth."""
    df = pd.DataFrame(dataset["rows"])
    return deps.keyword_svc.top_vs_bottom(df, dataset.get("metadata", []), views_col=views_col, top_n=top_n)


@router.get("/duration", response_model=DurationOut, response_model_exclude_unset=True)
def duration_analysis(dataset: deps.Dataset, metric: str = "Views") -> dict:
    """Group videos into duration buckets and summarise a metric for each."""
    df = pd.DataFrame(dataset["rows"])
    return deps.duration_svc.analyze(df, metric_col=metric)


@router.get("/descriptions", response_model=DescriptionsOut)
def descriptions(dataset: deps.Dataset) -> dict:
    """Per-video description facts (length, links, hashtags, timestamps)."""
    videos = deps.description_svc.analyze(dataset["rows"], dataset["video_id_col"])
    return {"videos": videos, "total": len(videos)}
