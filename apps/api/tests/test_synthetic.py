"""The fake-channel generator: deterministic, importable, and shaped like a real export."""
import pytest
from sqlalchemy import func, select

from db.models import Client, Upload, UploadTotal, Video
from ingest.importer import import_export
from synthetic.__main__ import MARKER, main, seed
from synthetic.generator import HEADERS, PROFILES, generate_rows, write_export


def test_same_seed_gives_the_same_rows():
    assert generate_rows(PROFILES[0]) == generate_rows(PROFILES[0])
    assert generate_rows(PROFILES[0]) != generate_rows(PROFILES[1])


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.name)
def test_rows_look_like_a_real_export(profile):
    rows = generate_rows(profile)
    total, videos = rows[0], rows[1:]
    col = {h: i for i, h in enumerate(HEADERS)}

    assert total[0] == "Total" and len(videos) == profile.videos
    assert all(len(r) == len(HEADERS) for r in rows)
    ids = [r[0] for r in videos]
    assert len(set(ids)) == len(ids) and all(len(i) == 11 for i in ids)
    assert sum(r[col["Views"]] for r in videos) == total[col["Views"]]
    # subscribers are partly credited to the channel, as in a real export
    assert total[col["Subscribers gained"]] > sum(r[col["Subscribers gained"]] for r in videos)


def test_shorts_have_no_impressions():
    rows = generate_rows(PROFILES[2])  # 70% Shorts
    impressions = [r[HEADERS.index("Impressions")] for r in rows[1:]]

    assert None in impressions and any(i is not None for i in impressions)


def test_exports_import_cleanly(tmp_path, catalog_session):
    client = Client(name="Fake")
    catalog_session.add(client)
    catalog_session.flush()
    path = write_export(PROFILES[1], tmp_path)

    result = import_export(catalog_session, client_id=client.id, path=path, filename=path.name, sha256="a" * 64)

    assert result.videos == PROFILES[1].videos
    assert result.new_unreviewed_metrics == []
    assert (result.period.kind, result.period.source) == ("range", "filename")


def test_seeding_is_repeatable(catalog_session):
    first = seed(catalog_session)
    second = seed(catalog_session)

    assert [r[2] for r in first] == [True] * 3 and [r[2] for r in second] == [False] * 3
    assert catalog_session.scalar(select(func.count()).select_from(Client).where(Client.notes == MARKER)) == 3
    assert catalog_session.scalar(select(func.count()).select_from(Upload)) == 3
    assert catalog_session.scalar(select(func.count()).select_from(Video)) == sum(p.videos for p in PROFILES)
    assert catalog_session.scalar(select(func.count()).select_from(UploadTotal)) > 0


def test_files_command_writes_one_export_per_channel(tmp_path):
    assert main(["files", str(tmp_path / "out")]) == 0

    assert len(list((tmp_path / "out").glob("*.xlsx"))) == len(PROFILES)
