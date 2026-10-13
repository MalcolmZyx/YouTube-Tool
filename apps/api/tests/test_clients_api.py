"""The client and upload routes, end to end, against a real Postgres."""
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from studio_fixtures import SIMPLE_HEADERS, simple_rows, write_xlsx

from app import app
from db.models import Client, Upload, UploadTotal, Video, VideoMetric
from db.session import get_session

CHANNEL_ID = "UC" + "x" * 22


@pytest.fixture
def api(catalog_session):
    """A client for the real app whose database work goes to the rolled-back test session."""
    app.dependency_overrides[get_session] = lambda: catalog_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def export_file(tmp_path):
    return write_xlsx(tmp_path / "Table data.xlsx", SIMPLE_HEADERS, simple_rows())


def create(api, name="Acme", **extra):
    response = api.post("/api/clients", json={"name": name, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def upload(api, client_id, path, filename=None, **form):
    with open(path, "rb") as fh:
        return api.post(
            f"/api/clients/{client_id}/uploads",
            files={"file": (filename or path.name, fh.read())},
            data=form,
        )


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


# ── transactions ────────────────────────────────────────────────────────────


def test_every_route_commits_before_the_response_is_sent():
    """Found by driving the real server: with the default dependency scope the commit ran after the response,
    so a DELETE could answer 200 and an immediate GET still return the client."""
    from fastapi.routing import APIRoute

    checked = 0
    for route in app.routes:
        if isinstance(route, APIRoute):
            for dependency in route.dependant.dependencies:
                if dependency.call is get_session:
                    assert dependency.scope == "function", f"{route.methods} {route.path}"
                    checked += 1

    assert checked >= 7  # every client and upload route


# ── clients ─────────────────────────────────────────────────────────────────


def test_create_and_read_a_client(api):
    created = create(api, "  Acme  ", youtube_channel_id=CHANNEL_ID, notes="first client")

    assert created["name"] == "Acme"  # surrounding whitespace is trimmed
    assert uuid.UUID(created["id"])  # a UUID, safe to put in a URL
    assert (created["upload_count"], created["video_count"]) == (0, 0)
    assert api.get(f"/api/clients/{created['id']}").json() == created


def test_clients_are_listed_newest_first_with_counts(api, catalog_session, export_file):
    older = create(api, "Older")
    newer = create(api, "Newer")
    upload(api, older["id"], export_file)
    # Postgres now() is the start of the *transaction*, and this whole test is one transaction, so both
    # rows were stamped identically. In real use each request is its own transaction; state the times.
    catalog_session.execute(
        update(Client).where(Client.id == uuid.UUID(older["id"])).values(created_at=func.now() - timedelta(days=1))
    )

    listing = api.get("/api/clients").json()

    assert [c["name"] for c in listing] == ["Newer", "Older"]
    assert listing[0]["id"] == newer["id"]
    assert (listing[1]["upload_count"], listing[1]["video_count"]) == (1, 3)


@pytest.mark.parametrize(
    "body",
    [{}, {"name": ""}, {"name": "   "}, {"name": "x" * 201}, {"name": "ok", "youtube_channel_id": "nope"}],
)
def test_invalid_clients_are_rejected(api, body):
    response = api.post("/api/clients", json=body)

    assert response.status_code == 422
    assert "error" in response.json()


def test_unknown_and_malformed_client_ids(api):
    assert api.get(f"/api/clients/{uuid.uuid4()}").status_code == 404
    assert api.get("/api/clients/not-a-uuid").status_code == 422
    assert api.delete(f"/api/clients/{uuid.uuid4()}").status_code == 404


# ── uploading ───────────────────────────────────────────────────────────────


def test_uploading_an_export_stores_it_under_the_client(api, catalog_session, export_file):
    client = create(api)

    response = upload(api, client["id"], export_file)

    assert response.status_code == 201
    body = response.json()
    assert (body["videos"], body["duplicate"], body["period_kind"]) == (3, False, "unknown")
    assert body["metric_values"] > 0 and body["total_values"] > 0
    assert count(catalog_session, Video) == 3
    assert api.get(f"/api/clients/{client['id']}").json()["upload_count"] == 1


def test_uploading_the_same_file_again_changes_nothing(api, catalog_session, export_file):
    client = create(api)
    first = upload(api, client["id"], export_file).json()
    before = (count(catalog_session, Upload), count(catalog_session, VideoMetric))

    response = upload(api, client["id"], export_file)

    assert response.status_code == 200  # not 201: nothing was created
    assert response.json()["duplicate"] is True
    assert response.json()["upload_id"] == first["upload_id"]
    assert (count(catalog_session, Upload), count(catalog_session, VideoMetric)) == before


def test_upload_for_an_unknown_client_is_404(api, export_file):
    assert upload(api, uuid.uuid4(), export_file).status_code == 404


def test_unsupported_and_unrecognised_files_get_clear_errors(api, tmp_path):
    client = create(api)
    wrong_type = tmp_path / "notes.txt"
    wrong_type.write_text("hello")
    other_report = write_xlsx(tmp_path / "traffic.xlsx", ["Traffic source", "Views"], [["YouTube search", 5]])
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"not a workbook")

    assert upload(api, client["id"], wrong_type).status_code == 400
    unrecognised = upload(api, client["id"], other_report)
    assert unrecognised.status_code == 422 and "Unrecognised export" in unrecognised.json()["error"]
    assert upload(api, client["id"], broken).status_code == 422


def test_a_failed_upload_leaves_no_trace(api, catalog_session, tmp_path):
    client = create(api)
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"not a workbook")
    upload(api, client["id"], broken)

    assert count(catalog_session, Upload) == 0


# ── the date range ──────────────────────────────────────────────────────────


def test_period_can_be_stated_on_upload(api, export_file):
    client = create(api)

    body = upload(api, client["id"], export_file, period_start="2026-01-01", period_end="2026-03-31").json()

    assert (body["period_kind"], body["period_start"], body["period_end"], body["period_source"]) == (
        "range", "2026-01-01", "2026-03-31", "user",
    )


def test_period_is_read_from_the_file_name_when_not_stated(api, export_file):
    client = create(api)

    body = upload(api, client["id"], export_file, filename="Table data 2026-01-01_2026-03-31.xlsx").json()

    assert (body["period_kind"], body["period_source"]) == ("range", "filename")


@pytest.mark.parametrize(
    "form",
    [
        {"period_start": "2026-01-01"},  # one date only
        {"period_start": "2026-03-31", "period_end": "2026-01-01"},  # backwards
        {"period_lifetime": "true", "period_start": "2026-01-01", "period_end": "2026-02-01"},  # contradictory
    ],
)
def test_inconsistent_periods_on_upload_are_rejected(api, export_file, form):
    client = create(api)

    assert upload(api, client["id"], export_file, **form).status_code == 422


def test_period_can_be_confirmed_afterwards(api, export_file):
    client = create(api)
    upload_id = upload(api, client["id"], export_file).json()["upload_id"]

    response = api.put(
        f"/api/clients/{client['id']}/uploads/{upload_id}/period",
        json={"kind": "range", "start": "2026-01-01", "end": "2026-06-30"},
    )

    assert response.status_code == 200
    assert (response.json()["period_kind"], response.json()["period_source"]) == ("range", "user")
    listed = api.get(f"/api/clients/{client['id']}/uploads").json()
    assert listed[0]["period_end"] == "2026-06-30"


@pytest.mark.parametrize(
    "body",
    [{"kind": "range"}, {"kind": "range", "start": "2026-02-01", "end": "2026-01-01"},
     {"kind": "lifetime", "start": "2026-01-01"}, {"kind": "weekly"}],
)
def test_invalid_period_confirmations_are_rejected(api, export_file, body):
    client = create(api)
    upload_id = upload(api, client["id"], export_file).json()["upload_id"]

    assert api.put(f"/api/clients/{client['id']}/uploads/{upload_id}/period", json=body).status_code == 422


def test_one_client_cannot_touch_anothers_upload(api, export_file):
    owner, intruder = create(api, "Owner"), create(api, "Intruder")
    upload_id = upload(api, owner["id"], export_file).json()["upload_id"]

    response = api.put(f"/api/clients/{intruder['id']}/uploads/{upload_id}/period", json={"kind": "lifetime"})

    assert response.status_code == 404
    assert api.get(f"/api/clients/{intruder['id']}/uploads").json() == []


# ── deleting a client ───────────────────────────────────────────────────────


def test_deleting_a_client_erases_its_data_and_reports_what_was_erased(api, catalog_session, export_file):
    doomed, keeper = create(api, "Doomed"), create(api, "Keeper")
    upload(api, doomed["id"], export_file)
    upload(api, keeper["id"], export_file)
    keeper_metrics = catalog_session.scalar(
        select(func.count()).select_from(VideoMetric).where(VideoMetric.client_id == uuid.UUID(keeper["id"]))
    )

    response = api.delete(f"/api/clients/{doomed['id']}")

    assert response.status_code == 200
    assert response.json()["deleted"] == {"uploads": 1, "videos": 3, "metric_values": keeper_metrics}
    assert api.get(f"/api/clients/{doomed['id']}").status_code == 404
    # Nothing of the deleted client remains, anywhere...
    gone = uuid.UUID(doomed["id"])
    for model in (Upload, Video, VideoMetric, UploadTotal):
        assert catalog_session.scalar(select(func.count()).select_from(model).where(model.client_id == gone)) == 0
    # ...and the other client is untouched.
    assert api.get(f"/api/clients/{keeper['id']}").json()["video_count"] == 3
    assert count(catalog_session, Client) == 1
