"""Characterization tests for services/analytics_service.py.

They pin down current behavior so later refactors (batching, FastAPI, Postgres) can be
checked against it.
"""
import math

import pandas as pd
import pytest
import requests
from services.analytics_service import (
    DataService,
    DescriptionService,
    DurationService,
    HeatmapService,
    KeywordService,
    convert_seconds_to_min_sec,
    get_video_info,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(301, "5:01"), (59, "0:59"), (60.0, "1:00"), ("125", "2:05"), ("abc", "abc"), (None, "None")],
)
def test_convert_seconds_to_min_sec(seconds, expected):
    assert convert_seconds_to_min_sec(seconds) == expected


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_get_video_info_requires_key_and_valid_id():
    assert get_video_info("AAAAAAAAAAA", "") is None
    assert get_video_info("short", "key") is None
    assert get_video_info("", "key") is None


def test_get_video_info_parses_snippet_and_prefers_largest_thumbnail(monkeypatch):
    payload = {
        "items": [
            {
                "snippet": {
                    "title": "T",
                    "description": "D",
                    "tags": ["a", "b"],
                    "categoryId": "20",
                    "thumbnails": {"default": {"url": "small"}, "high": {"url": "big"}},
                }
            }
        ]
    }
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(payload))
    info = get_video_info("AAAAAAAAAAA", "key")
    assert info == {
        "description": "D",
        "tags": ["a", "b"],
        "category_id": "20",
        "thumbnail_url": "big",
        "title": "T",
    }


def test_get_video_info_returns_none_when_video_missing_or_request_fails(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse({"items": []}))
    assert get_video_info("AAAAAAAAAAA", "key") is None

    def boom(*args, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "get", boom)
    assert get_video_info("AAAAAAAAAAA", "key") is None


# ---------------------------------------------------------------------------
# DataService
# ---------------------------------------------------------------------------


def test_load_file_separates_total_row_and_videos(studio_csv):
    result = DataService().load_file(studio_csv)

    assert result["video_id_col"] == "Content"
    assert [r["Content"] for r in result["rows"]] == ["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"]
    assert result["total_row"]["Content"] == "Total"
    assert result["total_row"]["Views"] == 600


def test_load_file_formats_duration_and_classifies_columns(studio_csv):
    result = DataService().load_file(studio_csv)

    assert [r["Duration (mins)"] for r in result["rows"]] == ["0:10", "2:00", "10:00"]
    assert "Views" in result["numeric_columns"]
    assert "Impressions click-through rate (%)" in result["percent_columns"]
    assert "Content" in result["text_columns"]


def test_load_file_drops_all_zero_columns(studio_csv):
    result = DataService().load_file(studio_csv)

    assert "Dislikes" not in result["columns"]
    assert "Dislikes" not in result["numeric_columns"]


def test_load_file_shares_sum_to_about_one_hundred(studio_csv):
    shares = DataService().load_file(studio_csv)["shares"]["Views"]

    assert sum(shares.values()) == pytest.approx(100, abs=0.5)
    assert shares[2] == 50.0  # 300 of 600 views


def test_load_file_without_key_leaves_metadata_empty(studio_csv):
    result = DataService().load_file(studio_csv)

    assert result["metadata"] == []
    assert all(r["thumbnail_url"] == "" for r in result["rows"])
    # hidden helper columns are not offered for display
    assert "thumbnail_url" not in result["columns"]
    assert "video_title" not in result["columns"]


def test_load_file_num_rows_limits_videos(studio_csv):
    result = DataService().load_file(studio_csv, num_rows=2)

    assert len(result["rows"]) == 2


def test_load_file_enriches_rows_when_api_returns_metadata(studio_csv, monkeypatch):
    def fake_info(video_id, api_key):
        return {
            "description": "desc " + video_id,
            "tags": ["t"],
            "category_id": "1",
            "thumbnail_url": "u",
            "title": "x",
        }

    monkeypatch.setattr("services.analytics_service.get_video_info", fake_info)
    result = DataService().load_file(studio_csv, api_key="key")

    assert len(result["metadata"]) == 3
    assert result["rows"][0]["video_description"] == "desc AAAAAAAAAAA"


# ---------------------------------------------------------------------------
# HeatmapService
# ---------------------------------------------------------------------------


def test_heatmap_sums_metric_per_day_and_reports_weekday_stats():
    df = pd.DataFrame(
        {
            "Video publish time": ["2024-01-01", "2024-01-01", "2024-01-03"],  # Mon, Mon, Wed
            "Views": [100, 200, 300],
        }
    )
    result = HeatmapService().compute(df)

    assert {r["date"]: r["value"] for r in result["calendar"]} == {"2024-01-01": 300, "2024-01-03": 300}
    monday = next(r for r in result["day_of_week"] if r["day"] == "Monday")
    assert monday["total"] == 300
    assert monday["avg"] == 150
    assert monday["count"] == 2


def test_heatmap_counts_videos_when_metric_missing():
    df = pd.DataFrame({"Video publish time": ["2024-01-01", "2024-01-01"]})
    result = HeatmapService().compute(df, metric_col="Nope")

    assert result["calendar"][0]["value"] == 2


def test_heatmap_empty_when_no_valid_dates():
    df = pd.DataFrame({"Video publish time": ["not a date"], "Views": [1]})

    assert HeatmapService().compute(df) == {"calendar": [], "day_of_week": []}


# ---------------------------------------------------------------------------
# KeywordService
# ---------------------------------------------------------------------------


def test_weighted_tags_scores_by_log_views_and_filters_stop_words_and_synonyms():
    df = pd.DataFrame(
        {
            "Views": [999, 99],
            "Tags": [["Minecraft", "video"], ["minecraft", "Mr Beast"]],
        }
    )
    scores = {t["tag"]: t["score"] for t in KeywordService().weighted_tags(df)}

    assert scores["minecraft"] == pytest.approx(math.log10(1000) + math.log10(100))  # 5.0
    assert scores["mrbeast"] == pytest.approx(2.0)  # synonym collapsed
    assert "video" not in scores  # stop word


def test_weighted_tags_accepts_json_and_comma_separated_strings():
    df = pd.DataFrame({"Views": [99, 99], "Tags": ['["a", "b"]', "a, c"]})
    scores = {t["tag"]: t["score"] for t in KeywordService().weighted_tags(df)}

    assert scores["a"] == pytest.approx(4.0)
    assert scores["b"] == pytest.approx(2.0)
    assert scores["c"] == pytest.approx(2.0)


def test_weighted_tags_respects_top_n():
    df = pd.DataFrame({"Views": [99], "Tags": [["a", "b", "c"]]})

    assert len(KeywordService().weighted_tags(df, top_n=2)) == 2


def test_top_vs_bottom_uses_top_and_bottom_fifth_of_videos():
    ids = [f"{c}" * 11 for c in "ABCDEFGHIJ"]
    df = pd.DataFrame({"Content": ids, "Views": [1000 - i * 100 for i in range(10)]})
    metadata = [{"video_id": vid, "tags": [f"tag{i}"]} for i, vid in enumerate(ids)]

    result = KeywordService().top_vs_bottom(df, metadata)

    assert {t["tag"] for t in result["top"]} == {"tag0", "tag1"}
    assert {t["tag"] for t in result["bottom"]} == {"tag8", "tag9"}


# ---------------------------------------------------------------------------
# DurationService
# ---------------------------------------------------------------------------


def test_duration_buckets_group_and_summarise():
    df = pd.DataFrame({"Duration": [5, 6, 10, 100], "Views": [10, 20, 30, 40]})
    buckets = {b["bucket"]: b for b in DurationService().analyze(df)["buckets"]}

    assert set(buckets) == {"0-7s", "8-15s", "1-4m"}
    assert buckets["0-7s"]["count"] == 2
    assert buckets["0-7s"]["mean"] == 15.0
    assert buckets["0-7s"]["median"] == 15.0
    assert buckets["0-7s"]["total"] == 30


def test_duration_adds_open_ended_buckets_for_long_videos():
    df = pd.DataFrame({"Duration": [1000], "Views": [5]})
    labels = [b["bucket"] for b in DurationService().analyze(df)["buckets"]]

    assert labels == ["15-20m"]


def test_duration_requires_columns():
    assert DurationService().analyze(pd.DataFrame({"Views": [1]})) == {"buckets": []}


# ---------------------------------------------------------------------------
# DescriptionService
# ---------------------------------------------------------------------------


def test_description_analysis_flags_links_hashtags_and_timestamps():
    rows = [
        {
            "Content": "AAAAAAAAAAA",
            "video_title": "Title",
            "video_description": "Watch https://x.com\n#tag 0:30 intro",
            "thumbnail_url": "u",
        },
        {"Content": "BBBBBBBBBBB", "video_description": ""},
        {"Content": "CCCCCCCCCCC", "video_description": "Failed to fetch"},
    ]
    out = DescriptionService().analyze(rows, "Content")

    assert len(out) == 1
    item = out[0]
    assert item["video_id"] == "AAAAAAAAAAA"
    assert item["title"] == "Title"
    assert item["url"] == "https://www.youtube.com/watch?v=AAAAAAAAAAA"
    assert item["line_count"] == 2
    assert item["has_links"] and item["has_hashtags"] and item["has_timestamps"]
