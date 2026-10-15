"""Pulling client uploads from the portal inbox: normal importer, judged one by one, never trusted."""
import hashlib
import json
import uuid
from urllib.parse import unquote

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from studio_fixtures import SIMPLE_HEADERS, simple_rows, write_csv, write_xlsx

from app import app
from config import settings
from db.models import Upload, Video
from db.session import get_session
from portal import client as portal
from synthetic.generator import PROFILES, write_export

KEY = "service-key-SECRET-123"


class FakeResponse:
    def __init__(self, status=200, body=None, content=b""):
        self.status_code, self._body, self._content = status, body if body is not None else [], content

    def json(self):
        return self._body

    def iter_content(self, size):
        for i in range(0, len(self._content), size):
            yield self._content[i:i + size]


class FakePortal:
    """The portal's inbox table and file store."""

    def __init__(self):
        self.rows, self.files, self.calls, self.fail_download = [], {}, [], False

    def add(self, client_id, filename, data, *, path=None, claimed_hash=None, size=None, name=None):
        path = path or f"{client_id}/{uuid.uuid4().hex}-{name or filename}"
        self.files[path] = data
        row = {"id": len(self.rows) + 1, "client_id": str(client_id), "storage_path": path,
               "original_filename": filename, "size_bytes": size if size is not None else len(data),
               "sha256": claimed_hash or hashlib.sha256(data).hexdigest(), "status": "pending", "message": None,
               "created_at": "2026-10-14T10:00:00+00:00"}
        self.rows.append(row)
        return row

    def __call__(self, method, url, params=None, headers=None, data=None, timeout=None, stream=False):
        self.calls.append((method, url))
        if "/storage/v1/object/inbox/" in url:
            path = unquote(url.split("/storage/v1/object/inbox/")[1])
            if self.fail_download:
                raise requests.ConnectionError(f"key={KEY} down")
            if path not in self.files:
                return FakeResponse(404)
            if method == "DELETE":
                del self.files[path]
                return FakeResponse(200)
            return FakeResponse(content=self.files[path])
        table = url.split("/rest/v1/")[1]
        if table == "upload_inbox" and method == "GET":
            wanted = params["status"].removeprefix("eq.")
            return FakeResponse(body=[r for r in self.rows if r["status"] == wanted])
        if table == "upload_inbox" and method == "PATCH":
            body = json.loads(data)
            for r in self.rows:
                if r["id"] == int(params["id"].removeprefix("eq.")):
                    r.update(body)
            return FakeResponse(204)
        raise AssertionError(f"unexpected portal call {method} {url}")


@pytest.fixture
def api(catalog_session):
    app.dependency_overrides[get_session] = lambda: catalog_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def fake(monkeypatch):
    fake_portal = FakePortal()
    monkeypatch.setattr(settings, "portal_url", "http://portal.test")
    monkeypatch.setenv("PORTAL_SERVICE_KEY", KEY)
    monkeypatch.setattr(requests, "request", fake_portal)
    return fake_portal


@pytest.fixture
def client_id(api):
    return api.post("/api/clients", json={"name": "Acme"}).json()["id"]


def pull(api):
    response = api.post("/api/portal/inbox/pull")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def good_csv(tmp_path):
    return write_csv(tmp_path / "Table data.csv", SIMPLE_HEADERS, simple_rows()).read_bytes()


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_a_waiting_upload_is_listed_with_the_client_name(api, client_id, fake, good_csv):
    fake.add(client_id, "export.csv", good_csv)

    (item,) = api.get("/api/portal/inbox").json()

    assert (item["client_name"], item["original_filename"]) == ("Acme", "export.csv")
    assert "storage_path" not in item and "sha256" not in item


def test_pulling_imports_through_the_normal_importer_and_cleans_up(api, client_id, fake, good_csv, catalog_session):
    row = fake.add(client_id, "export.csv", good_csv)

    (outcome,) = pull(api)

    assert (outcome["result"], outcome["detail"]) == ("imported", "Imported 3 videos.")
    assert count(catalog_session, Video) == 3 and count(catalog_session, Upload) == 1
    assert row["status"] == "pulled" and row["message"] == "Imported 3 videos."  # what the client reads
    assert fake.files == {}  # the file is no longer online
    assert pull(api) == []  # nothing left to pull


def test_xlsx_files_work_too(api, client_id, fake, tmp_path, catalog_session):
    fake.add(client_id, "export.xlsx", write_export(PROFILES[1], tmp_path).read_bytes())

    assert pull(api)[0]["result"] == "imported" and count(catalog_session, Video) == PROFILES[1].videos


def test_the_same_file_twice_is_recognised(api, client_id, fake, good_csv, catalog_session):
    fake.add(client_id, "a.csv", good_csv)
    fake.add(client_id, "again.csv", good_csv)

    results = [o["result"] for o in pull(api)]

    assert results == ["imported", "duplicate"] and count(catalog_session, Upload) == 1


def test_a_file_that_is_not_an_export_is_rejected_with_a_reason_and_removed(api, client_id, fake, tmp_path):
    other = write_xlsx(tmp_path / "t.xlsx", ["Traffic source", "Views"], [["Search", 5]]).read_bytes()
    row = fake.add(client_id, "traffic.xlsx", other)

    (outcome,) = pull(api)

    assert outcome["result"] == "rejected" and "Unrecognised export" in outcome["detail"]
    assert row["status"] == "rejected" and "Unrecognised" in row["message"] and fake.files == {}


@pytest.mark.parametrize("filename", ["macro.xlsm", "run.exe", "notes.txt", "noextension", "old.xls"])
def test_only_csv_and_xlsx_are_accepted(api, client_id, fake, good_csv, filename):
    row = fake.add(client_id, filename, good_csv)

    assert pull(api)[0]["result"] == "rejected" and row["status"] == "rejected"
    assert not any(c[0] == "GET" and "/storage/" in c[1] for c in fake.calls)  # never even downloaded


def test_a_corrupt_workbook_is_rejected_not_a_crash(api, client_id, fake):
    fake.add(client_id, "broken.xlsx", b"not a workbook")

    assert pull(api)[0]["result"] == "rejected"


def test_a_file_that_does_not_match_its_hash_is_rejected(api, client_id, fake, good_csv, catalog_session):
    fake.add(client_id, "export.csv", good_csv, claimed_hash="0" * 64)

    (outcome,) = pull(api)

    assert outcome["result"] == "rejected" and "intact" in outcome["detail"] and count(catalog_session, Video) == 0


def test_an_oversized_file_is_rejected_by_its_declared_and_its_real_size(api, client_id, fake, good_csv, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 0)  # everything is now too big
    fake.add(client_id, "declared.csv", good_csv, size=10**9)
    fake.add(client_id, "real.csv", good_csv, size=1)

    assert [o["result"] for o in pull(api)] == ["rejected", "rejected"]


@pytest.mark.parametrize("path_for", [
    lambda mine, other: f"{mine}/../{other}/secret.csv",
    lambda mine, other: f"{other}/secret.csv",  # another client's folder
    lambda mine, other: f"{mine}/sub/dir.csv",
    lambda mine, other: "secret.csv",
    lambda mine, other: f"{mine}/..",
    lambda mine, other: f"{mine}\\evil.csv",
])
def test_a_crafted_storage_path_is_never_downloaded(api, client_id, fake, good_csv, path_for):
    other = api.post("/api/clients", json={"name": "Other"}).json()["id"]
    fake.add(client_id, "export.csv", good_csv, path=path_for(client_id, other))

    (outcome,) = pull(api)

    assert outcome["result"] == "rejected"
    assert not any("/storage/" in c[1] for c in fake.calls)  # the service key was never used on that path


def test_an_upload_for_a_client_that_no_longer_exists_is_skipped_and_left_alone(api, fake, good_csv):
    row = fake.add(uuid.uuid4(), "export.csv", good_csv)

    (outcome,) = pull(api)

    assert outcome["result"] == "skipped" and row["status"] == "pending" and len(fake.files) == 1


def test_one_bad_file_does_not_block_the_good_ones(api, client_id, fake, good_csv, catalog_session):
    fake.add(client_id, "broken.xlsx", b"junk")
    fake.add(client_id, "export.csv", good_csv)

    assert [o["result"] for o in pull(api)] == ["rejected", "imported"]
    assert count(catalog_session, Video) == 3


def test_a_portal_outage_while_downloading_leaves_the_upload_pending(api, client_id, fake, good_csv):
    row = fake.add(client_id, "export.csv", good_csv)
    fake.fail_download = True

    (outcome,) = pull(api)

    assert outcome["result"] == "skipped" and row["status"] == "pending"
    assert KEY not in json.dumps(outcome)


def test_the_hostile_file_name_is_only_ever_data(api, client_id, fake, good_csv):
    name = '<img src=x onerror=alert(1)>"; drop table x;--.csv'
    fake.add(client_id, name, good_csv, name="safe.csv")

    (outcome,) = pull(api)

    assert outcome["result"] == "imported" and outcome["filename"] == name


def test_pulling_needs_the_portal_to_be_configured(api, client_id):
    assert api.post("/api/portal/inbox/pull").status_code == 503
    assert api.get("/api/portal/inbox").status_code == 503


def test_safe_storage_path_accepts_only_the_clients_own_folder():
    me = uuid.uuid4()

    assert portal.safe_storage_path(me, f"{me}/abc-export.csv")
    for bad in (f"{me}/", f"{me}/.", f"{me}/..", f"{me}//x", f"{uuid.uuid4()}/x.csv", f"{me}/a/b", "x"):
        assert not portal.safe_storage_path(me, bad), bad
