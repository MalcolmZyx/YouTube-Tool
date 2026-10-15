"""Database tests: the guarantees the schema is designed to give.

Every test here runs against a real Postgres (see the database fixtures in conftest.py), because
the guarantees are enforced by the database itself: foreign keys, cascades and CHECK constraints.
"""
import datetime
import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from studio_fixtures import STUDIO_METRIC_HEADERS

from db.base import Base
from db.catalog import find_metric_key, get_or_register_metric, normalize_header, sync_metric_catalog
from db.models import (
    Client,
    Metric,
    MetricAlias,
    Upload,
    UploadTotal,
    Video,
    VideoMetric,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
CHANNEL_ID = "UC" + "x" * 22


# ── helpers ─────────────────────────────────────────────────────────────────


def make_client(session, name="Client") -> Client:
    client = Client(name=name)
    session.add(client)
    session.flush()
    return client


def make_upload(session, client, sha=SHA_A, **overrides) -> Upload:
    fields = {"report_type": "table_data", "original_filename": "export.xlsx", "file_sha256": sha}
    upload = Upload(client_id=client.id, **{**fields, **overrides})
    session.add(upload)
    session.flush()
    return upload


def make_video(session, client, youtube_id="AAAAAAAAAAA") -> Video:
    video = Video(client_id=client.id, youtube_video_id=youtube_id, title="A video")
    session.add(video)
    session.flush()
    return video


def assert_rejected(session, obj):
    """The database must refuse this row (constraint violation or a value that does not fit the column).

    A savepoint keeps the surrounding test transaction usable afterwards.
    """
    with pytest.raises(DBAPIError), session.begin_nested():
        session.add(obj)
        session.flush()


def count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


# ── migrations ──────────────────────────────────────────────────────────────


def test_migrations_and_models_agree(db_engine):
    """If this fails, a model changed without a migration (or the reverse)."""
    with db_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []


# ── cascade delete: the "delete my data" promise ────────────────────────────


def test_deleting_a_client_removes_everything_that_belongs_to_it(catalog_session):
    session = catalog_session
    mine = make_client(session, "Delete me")
    other = make_client(session, "Keep me")

    for client, sha, ytid in ((mine, SHA_A, "AAAAAAAAAAA"), (other, SHA_B, "BBBBBBBBBBB")):
        upload = make_upload(session, client, sha)
        video = make_video(session, client, ytid)
        session.add_all(
            [
                VideoMetric(client_id=client.id, upload_id=upload.id, video_id=video.id, metric_key="views", value=10),
                UploadTotal(client_id=client.id, upload_id=upload.id, metric_key="views", value=10),
            ]
        )
    session.flush()

    session.delete(mine)
    session.flush()

    for model in (Upload, Video, VideoMetric, UploadTotal):
        assert count(session, model) == 1, f"{model.__name__} should keep only the other client's row"
    assert session.scalar(select(Client.name)) == "Keep me"
    assert count(session, Metric) > 0  # shared reference data is untouched


# ── tenant isolation: composite foreign keys ────────────────────────────────


def test_metric_cannot_link_one_clients_upload_to_anothers_video(catalog_session):
    session = catalog_session
    alice, bob = make_client(session, "Alice"), make_client(session, "Bob")
    alice_upload = make_upload(session, alice, SHA_A)
    bob_video = make_video(session, bob, "BBBBBBBBBBB")

    # Both ids exist, but they belong to different clients. Plain foreign keys would accept this.
    assert_rejected(
        session,
        VideoMetric(client_id=alice.id, upload_id=alice_upload.id, video_id=bob_video.id, metric_key="views", value=1),
    )


def test_metric_cannot_claim_the_wrong_client(catalog_session):
    session = catalog_session
    alice, bob = make_client(session, "Alice"), make_client(session, "Bob")
    upload, video = make_upload(session, alice), make_video(session, alice)

    assert_rejected(
        session, VideoMetric(client_id=bob.id, upload_id=upload.id, video_id=video.id, metric_key="views", value=1)
    )


# ── uniqueness ──────────────────────────────────────────────────────────────


def test_same_file_cannot_be_imported_twice_for_one_client(db_session):
    client = make_client(db_session)
    make_upload(db_session, client, SHA_A)

    duplicate = Upload(client_id=client.id, report_type="table_data", original_filename="x", file_sha256=SHA_A)

    assert_rejected(db_session, duplicate)


def test_same_file_can_be_imported_for_different_clients(db_session):
    make_upload(db_session, make_client(db_session, "One"), SHA_A)
    make_upload(db_session, make_client(db_session, "Two"), SHA_A)

    assert count(db_session, Upload) == 2


def test_a_video_appears_once_per_client_but_may_appear_for_several_clients(db_session):
    one, two = make_client(db_session, "One"), make_client(db_session, "Two")
    make_video(db_session, one)
    make_video(db_session, two)  # same YouTube id, different client: allowed

    assert_rejected(db_session, Video(client_id=one.id, youtube_video_id="AAAAAAAAAAA"))


def test_one_value_per_video_upload_and_metric(catalog_session):
    session = catalog_session
    client = make_client(session)
    upload, video = make_upload(session, client), make_video(session, client)
    row = {"client_id": client.id, "upload_id": upload.id, "video_id": video.id, "metric_key": "views"}
    session.add(VideoMetric(value=1, **row))
    session.flush()

    assert_rejected(session, VideoMetric(value=2, **row))


# ── CHECK constraints ───────────────────────────────────────────────────────

VALID_PERIODS = [
    {"period_kind": "unknown"},
    {"period_kind": "lifetime"},
    {"period_kind": "range", "period_start": datetime.date(2026, 1, 1), "period_end": datetime.date(2026, 3, 31)},
    {"period_kind": "range", "period_start": datetime.date(2026, 1, 1), "period_end": datetime.date(2026, 1, 1)},
]
INVALID_PERIODS = [
    {"period_kind": "range"},  # a range needs both dates
    {"period_kind": "range", "period_start": datetime.date(2026, 1, 1)},
    {"period_kind": "range", "period_start": datetime.date(2026, 3, 31), "period_end": datetime.date(2026, 1, 1)},
    {"period_kind": "lifetime", "period_start": datetime.date(2026, 1, 1), "period_end": datetime.date(2026, 3, 1)},
    {"period_kind": "unknown", "period_start": datetime.date(2026, 1, 1)},
    {"period_kind": "weekly"},
]


@pytest.mark.parametrize("period", VALID_PERIODS)
def test_valid_periods_are_accepted(db_session, period):
    make_upload(db_session, make_client(db_session), **period)


@pytest.mark.parametrize("period", INVALID_PERIODS)
def test_inconsistent_periods_are_rejected(db_session, period):
    client = make_client(db_session)

    assert_rejected(
        db_session,
        Upload(client_id=client.id, report_type="table_data", original_filename="x", file_sha256=SHA_A, **period),
    )


@pytest.mark.parametrize("youtube_id", ["short", "toolongtoolong", "bad!chars!!", ""])
def test_youtube_ids_must_be_eleven_url_safe_characters(db_session, youtube_id):
    client = make_client(db_session)

    assert_rejected(db_session, Video(client_id=client.id, youtube_video_id=youtube_id))


def test_blank_client_names_and_malformed_channel_ids_are_rejected(db_session):
    assert_rejected(db_session, Client(name="   "))
    assert_rejected(db_session, Client(name="x", youtube_channel_id="not-a-channel"))
    db_session.add(Client(name="ok", youtube_channel_id=CHANNEL_ID))
    db_session.flush()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_metric_values_must_be_finite(catalog_session, value):
    session = catalog_session
    client = make_client(session)
    upload, video = make_upload(session, client), make_video(session, client)

    bad = VideoMetric(client_id=client.id, upload_id=upload.id, video_id=video.id, metric_key="views", value=value)

    assert_rejected(session, bad)


@pytest.mark.parametrize("value", [0.0, -2.0, 1e12])
def test_zero_negative_and_large_values_are_valid(catalog_session, value):
    """Zero means 'reported as zero'; a negative is real (net subscribers); only non-finite numbers are errors."""
    session = catalog_session
    client = make_client(session)
    upload, video = make_upload(session, client), make_video(session, client)
    key = {"client_id": client.id, "upload_id": upload.id, "video_id": video.id}
    session.add(VideoMetric(metric_key="subscribers_net", value=value, **key))
    session.flush()


def test_metrics_must_exist_in_the_catalog(catalog_session):
    session = catalog_session
    client = make_client(session)
    upload, video = make_upload(session, client), make_video(session, client)

    assert_rejected(
        session,
        VideoMetric(client_id=client.id, upload_id=upload.id, video_id=video.id, metric_key="not_a_metric", value=1),
    )


# ── metric catalog ──────────────────────────────────────────────────────────


def _metric(**fields):
    base = {"key": "x", "display_name": "X", "family": "f", "unit": "count", "aggregation": "sum"}
    return Metric(**{**base, **fields})


@pytest.mark.parametrize(
    "fields",
    [
        {"aggregation": "ratio"},  # a ratio needs a numerator and a denominator
        {"aggregation": "ratio", "numerator_key": "views"},
        {"aggregation": "weighted_avg"},  # a weighted average needs a weight
        {"aggregation": "sum", "weight_key": "views"},  # a weight on a plain sum makes no sense
        {"key": "Bad Key"},
        {"unit": "furlongs"},
        {"aggregation": "median"},
    ],
)
def test_catalog_rules_are_enforced(catalog_session, fields):
    assert_rejected(catalog_session, _metric(**fields))


def test_catalog_sync_is_idempotent(db_session):
    first = sync_metric_catalog(db_session)
    metrics, aliases = count(db_session, Metric), count(db_session, MetricAlias)
    second = sync_metric_catalog(db_session)

    assert first == second > 50
    assert (count(db_session, Metric), count(db_session, MetricAlias)) == (metrics, aliases)


def test_every_ratio_and_weight_points_at_a_seeded_metric(catalog_session):
    keys = set(catalog_session.scalars(select(Metric.key)))
    for metric in catalog_session.scalars(select(Metric)):
        for ref in (metric.numerator_key, metric.denominator_key, metric.weight_key):
            assert ref is None or ref in keys, (metric.key, ref)


def test_every_column_of_a_real_export_is_recognised(catalog_session):
    unknown = [h for h in STUDIO_METRIC_HEADERS if find_metric_key(catalog_session, h) is None]

    assert unknown == []
    assert len(STUDIO_METRIC_HEADERS) == 48


def test_header_matching_ignores_case_and_spacing(catalog_session):
    assert find_metric_key(catalog_session, "  IMPRESSIONS   click-through   RATE (%) ") == "impressions_ctr_pct"
    assert normalize_header("A  B\tC") == "a b c"


def test_unknown_columns_are_kept_and_flagged_for_review(catalog_session):
    key = get_or_register_metric(catalog_session, "Shorts feed swipe-aways (new!)")

    metric = catalog_session.get(Metric, key)
    assert key == "shorts_feed_swipe_aways_new"
    assert (metric.review_status, metric.family, metric.aggregation) == ("unreviewed", "unmapped", "none")
    assert get_or_register_metric(catalog_session, "SHORTS feed  swipe-aways (new!)") == key  # same header, same key


def test_known_columns_are_not_re_registered(catalog_session):
    before = count(catalog_session, Metric)

    assert get_or_register_metric(catalog_session, "Views") == "views"
    assert count(catalog_session, Metric) == before


def test_different_headers_that_slug_alike_get_distinct_keys(catalog_session):
    first = get_or_register_metric(catalog_session, "Foo (%)")
    second = get_or_register_metric(catalog_session, "foo %")
    third = get_or_register_metric(catalog_session, "3D views")

    assert len({first, second, third}) == 3
    assert third == "m_3d_views"  # keys must start with a letter


def test_a_key_is_never_the_name_of_a_non_metric_column(db_session):
    """The descriptive columns are handled by the importer, not registered as metrics."""
    from db.catalog import ATTRIBUTE_HEADERS

    assert {"content", "video title", "video publish time", "duration"} == ATTRIBUTE_HEADERS


def test_ids_are_uuids_for_clients_and_integers_elsewhere(db_session):
    client = make_client(db_session)
    upload = make_upload(db_session, client)

    assert isinstance(client.id, uuid.UUID)
    assert isinstance(upload.id, int)
