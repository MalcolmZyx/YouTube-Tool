"""The importer against a real Postgres: what lands in which table, and what must not."""
import datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from studio_fixtures import (
    FULL_HEADERS,
    ID_A,
    ID_B,
    ID_C,
    SIMPLE_HEADERS,
    full_export,
    simple_rows,
    write_csv,
    write_xlsx,
)

from db.models import Client, Metric, Upload, UploadTotal, Video, VideoMetric
from ingest.importer import ImportRejected, Period, import_export

SHA_1, SHA_2, SHA_3 = "1" * 64, "2" * 64, "3" * 64


@pytest.fixture
def session(catalog_session):
    return catalog_session


@pytest.fixture
def client(session):
    client = Client(name="Test client")
    session.add(client)
    session.flush()
    return client


def run(session, client, path, *, sha=SHA_1, filename=None, **options):
    return import_export(
        session, client_id=client.id, path=str(path), filename=filename or Path(path).name, sha256=sha, **options
    )


def values_for(session, upload_id, youtube_id=None, key=None):
    query = (
        select(Video.youtube_video_id, VideoMetric.metric_key, VideoMetric.value)
        .join(Video, Video.id == VideoMetric.video_id)
        .where(VideoMetric.upload_id == upload_id)
    )
    if youtube_id:
        query = query.where(Video.youtube_video_id == youtube_id)
    if key:
        query = query.where(VideoMetric.metric_key == key)
    return {(yid, k): v for yid, k, v in session.execute(query)}


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


# ── what is stored ──────────────────────────────────────────────────────────


def test_videos_values_and_totals_land_in_their_own_tables(session, client, tmp_path):
    path = write_xlsx(tmp_path / "export.xlsx", SIMPLE_HEADERS, simple_rows())

    result = run(session, client, path)

    assert (result.videos, result.duplicate) == (3, False)
    assert count(session, Video) == 3  # the Total row is not a video
    assert session.scalar(select(Video.title).where(Video.youtube_video_id == ID_A)) == "First"
    assert values_for(session, result.upload_id, ID_B, "views") == {(ID_B, "views"): 200.0}
    totals = dict(session.execute(select(UploadTotal.metric_key, UploadTotal.value)).all())
    assert totals == {"views": 600.0, "likes": 30.0}


def test_video_attributes_are_parsed(session, client, tmp_path):
    result = run(session, client, write_xlsx(tmp_path / "e.xlsx", SIMPLE_HEADERS, simple_rows()))

    video = session.scalar(select(Video).where(Video.youtube_video_id == ID_C))
    assert (video.published_on, video.duration_seconds) == (datetime.date(2024, 1, 3), 600)
    assert session.get(Upload, result.upload_id).row_count == 3


def test_not_reported_is_stored_as_nothing_and_zero_as_zero(session, client, tmp_path):
    # Video C has no Likes (blank) and video B reports 0 likes.
    result = run(session, client, write_xlsx(tmp_path / "e.xlsx", SIMPLE_HEADERS, simple_rows()))

    likes = values_for(session, result.upload_id, key="likes")
    assert likes == {(ID_A, "likes"): 5.0, (ID_B, "likes"): 0.0}  # C is absent, B is a real zero


def test_csv_text_cells_are_understood(session, client, tmp_path):
    rows = [
        ["Total", "", "", "", "1,000", "4.5%", "00:00:30"],
        [ID_A, "A", "2024-01-01", "10", "1,000", "4.75%", "00:00:56"],
    ]
    headers = [
        "Content", "Video title", "Video publish time", "Duration", "Views",
        "Impressions click-through rate (%)", "Average view duration",
    ]
    result = run(session, client, write_csv(tmp_path / "e.csv", headers, rows))

    stored = values_for(session, result.upload_id, ID_A)
    assert stored[(ID_A, "views")] == 1000.0
    assert stored[(ID_A, "impressions_ctr_pct")] == 4.75
    assert stored[(ID_A, "avg_view_duration_seconds")] == 56.0


def test_a_full_real_shaped_export_is_imported_without_surprises(session, client, tmp_path):
    result = run(session, client, full_export(tmp_path / "full.xlsx"))

    assert result.videos == 2
    assert result.new_unreviewed_metrics == []  # every one of the 48 columns is in the catalog
    assert result.metric_values == 2 * 48
    assert result.total_values == 48
    duration = values_for(session, result.upload_id, ID_A, "avg_view_duration_seconds")
    assert duration == {(ID_A, "avg_view_duration_seconds"): 56.0}


# ── idempotency and re-import ───────────────────────────────────────────────


def test_the_same_file_is_not_imported_twice(session, client, tmp_path):
    path = write_xlsx(tmp_path / "e.xlsx", SIMPLE_HEADERS, simple_rows())
    first = run(session, client, path)
    before = (count(session, Upload), count(session, VideoMetric), count(session, Video))

    second = run(session, client, path)

    assert second.duplicate and second.upload_id == first.upload_id
    assert (second.videos, second.metric_values) == (3, first.metric_values)
    assert (count(session, Upload), count(session, VideoMetric), count(session, Video)) == before


def test_a_new_file_for_known_videos_adds_an_upload_and_refreshes_attributes(session, client, tmp_path):
    first = run(session, client, write_xlsx(tmp_path / "a.xlsx", SIMPLE_HEADERS, simple_rows()), sha=SHA_1)
    newer = simple_rows(total_views=900)
    newer[1][1] = "First (renamed)"
    newer[2][1] = None  # a blank title must not erase the one we already know
    second = run(session, client, write_xlsx(tmp_path / "b.xlsx", SIMPLE_HEADERS, newer), sha=SHA_2)

    assert second.upload_id != first.upload_id
    assert count(session, Video) == 3  # same videos, not duplicated
    assert session.scalar(select(Video.title).where(Video.youtube_video_id == ID_A)) == "First (renamed)"
    assert session.scalar(select(Video.title).where(Video.youtube_video_id == ID_B)) == "Second"
    assert count(session, Upload) == 2


def test_the_same_file_can_be_imported_for_two_clients(session, tmp_path):
    path = write_xlsx(tmp_path / "e.xlsx", SIMPLE_HEADERS, simple_rows())
    one, two = Client(name="One"), Client(name="Two")
    session.add_all([one, two])
    session.flush()

    assert not run(session, one, path).duplicate
    assert not run(session, two, path).duplicate
    assert count(session, Video) == 6


# ── unknown and awkward input ───────────────────────────────────────────────


def test_unknown_columns_are_kept_and_flagged(session, client, tmp_path):
    headers = [*SIMPLE_HEADERS, "Shorts swipe-aways"]
    rows = [[*r, 7 if i else 70] for i, r in enumerate(simple_rows())]

    result = run(session, client, write_xlsx(tmp_path / "e.xlsx", headers, rows))

    assert result.new_unreviewed_metrics == ["shorts_swipe_aways"]
    assert any("unreviewed" in w for w in result.warnings)
    assert session.get(Metric, "shorts_swipe_aways").review_status == "unreviewed"
    assert values_for(session, result.upload_id, ID_A, "shorts_swipe_aways")[(ID_A, "shorts_swipe_aways")] == 7.0


def test_invalid_and_repeated_video_ids_are_skipped_with_warnings(session, client, tmp_path):
    rows = [
        [ID_A, "A", None, 10, 1, 1],
        ["short", "bad", None, 10, 1, 1],
        [None, "blank", None, 10, 1, 1],
        [ID_A, "A again", None, 10, 99, 1],
    ]
    result = run(session, client, write_xlsx(tmp_path / "e.xlsx", SIMPLE_HEADERS, rows))

    assert result.videos == 1
    assert values_for(session, result.upload_id, ID_A, "views") == {(ID_A, "views"): 1.0}  # the first row wins
    text = " ".join(result.warnings)
    assert "not valid" in text and "more than once" in text


def test_cells_that_are_not_numbers_are_skipped_with_a_warning(session, client, tmp_path):
    # Markers like "n/a" are read as missing by pandas, so use text that is clearly not a number.
    rows = [[ID_A, "A", None, 10, "abc", 5], [ID_B, "B", None, 10, 20, 5]]
    result = run(session, client, write_xlsx(tmp_path / "e.xlsx", SIMPLE_HEADERS, rows))

    assert values_for(session, result.upload_id, key="views") == {(ID_B, "views"): 20.0}
    assert any("not numbers" in w for w in result.warnings)


def test_two_columns_for_one_metric_keep_the_first(session, client, tmp_path):
    headers = ["Content", "Impressions", "Thumbnail impressions"]
    result = run(session, client, write_csv(tmp_path / "e.csv", headers, [[ID_A, 100, 999]]))

    assert values_for(session, result.upload_id, key="impressions") == {(ID_A, "impressions"): 100.0}
    assert any("same metric" in w for w in result.warnings)


# ── refusing files ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("headers", "message"),
    [
        (["Traffic source", "Views"], "Unrecognised export"),
        (["Content", "Views"], "No video rows"),  # a Content column but no valid videos
    ],
)
def test_unusable_files_are_rejected_with_a_reason(session, client, tmp_path, headers, message):
    rows = [["YouTube search", 5]] if headers[0] != "Content" else [["not-an-id", 5]]
    path = write_xlsx(tmp_path / "e.xlsx", headers, rows)

    with pytest.raises(ImportRejected, match=message):
        run(session, client, path)


def test_an_unreadable_file_is_rejected(session, client, tmp_path):
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"this is not a workbook")

    with pytest.raises(ImportRejected, match="Could not read"):
        run(session, client, path)


def test_an_empty_file_is_rejected(session, client, tmp_path):
    with pytest.raises(ImportRejected, match="no data rows"):
        run(session, client, write_csv(tmp_path / "e.csv", ["Content", "Views"], []))


def test_too_many_videos_is_a_413(session, client, tmp_path):
    path = write_xlsx(tmp_path / "e.xlsx", SIMPLE_HEADERS, simple_rows())

    with pytest.raises(ImportRejected) as excinfo:
        run(session, client, path, max_rows=2)

    assert excinfo.value.status_code == 413


def test_a_rejected_import_leaves_nothing_behind_when_rolled_back(session, client, tmp_path):
    savepoint = session.begin_nested()
    with pytest.raises(ImportRejected):
        run(session, client, write_xlsx(tmp_path / "e.xlsx", SIMPLE_HEADERS, simple_rows()), max_rows=2)
    savepoint.rollback()

    assert count(session, Upload) == 0
    assert count(session, Video) == 0


# ── the date range ──────────────────────────────────────────────────────────


def test_period_is_unknown_unless_stated_or_found_in_the_file_name(session, client, tmp_path):
    result = run(session, client, write_xlsx(tmp_path / "e.xlsx", SIMPLE_HEADERS, simple_rows()))

    assert result.period == Period("unknown")
    assert session.get(Upload, result.upload_id).period_kind == "unknown"


def test_period_is_read_from_the_file_name(session, client, tmp_path):
    path = write_xlsx(tmp_path / "e.xlsx", SIMPLE_HEADERS, simple_rows())
    result = run(session, client, path, filename="Table data 2026-01-01_2026-03-31 Channel.xlsx")

    upload = session.get(Upload, result.upload_id)
    assert (upload.period_kind, upload.period_start, upload.period_end, upload.period_source) == (
        "range", datetime.date(2026, 1, 1), datetime.date(2026, 3, 31), "filename",
    )


def test_a_stated_period_beats_the_file_name(session, client, tmp_path):
    path = write_xlsx(tmp_path / "e.xlsx", SIMPLE_HEADERS, simple_rows())
    stated = Period("lifetime", source="user")
    result = run(session, client, path, filename="x 2026-01-01_2026-03-31.xlsx", period=stated,
                 exported_on=datetime.date(2026, 4, 1))

    upload = session.get(Upload, result.upload_id)
    assert (upload.period_kind, upload.period_source) == ("lifetime", "user")
    assert upload.exported_on == datetime.date(2026, 4, 1)


# ── reconciling with the Total row ──────────────────────────────────────────


def test_a_total_that_the_videos_do_not_add_up_to_is_flagged(session, client, tmp_path):
    result = run(session, client, write_xlsx(tmp_path / "e.xlsx", SIMPLE_HEADERS, simple_rows(total_views=5000)))

    assert any("Views" in w and "add up" in w for w in result.warnings)


def test_a_total_that_matches_is_not_flagged(session, client, tmp_path):
    result = run(session, client, write_xlsx(tmp_path / "e.xlsx", SIMPLE_HEADERS, simple_rows(total_views=600)))

    assert not any("add up" in w and "Views" in w for w in result.warnings)


# ── your own export, when it is on this machine ─────────────────────────────

REAL_EXPORT = Path(__file__).resolve().parents[3] / "yt_table_data.xlsx"


@pytest.mark.skipif(not REAL_EXPORT.exists(), reason="the real export is git-ignored and only on the owner's machine")
def test_the_real_export_imports_cleanly(session, client):
    result = run(session, client, REAL_EXPORT)

    assert result.videos > 0
    assert result.new_unreviewed_metrics == []
    assert result.total_values > 0


def test_full_headers_constant_matches_the_real_column_count():
    assert len(FULL_HEADERS) == 52
