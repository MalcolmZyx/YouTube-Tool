"""Portal isolation: can one client see or change another's data? These tests try to break the policies.

They run against the LOCAL Supabase database (`npx supabase start` from the repo root, which applies
supabase/migrations). Each test works inside a transaction that is rolled back, and acts as a signed-in user the
standard way: `set local role authenticated` plus the user's id in the JWT claims. Skipped when the local stack is not
running, unless REQUIRE_PORTAL_DB=1.
"""
import json
import os
import uuid

import psycopg
import pytest
from psycopg import errors

PORTAL_DB_URL = os.environ.get("PORTAL_DB_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres")
SHA = "a" * 64


@pytest.fixture(scope="module")
def portal_connection():
    try:
        conn = psycopg.connect(PORTAL_DB_URL, connect_timeout=3)
    except psycopg.OperationalError:
        if os.environ.get("REQUIRE_PORTAL_DB") == "1":
            raise
        pytest.skip("local Supabase is not running (npx supabase start)")
    with conn.cursor() as cur:
        cur.execute("select to_regclass('public.published_snapshot')")
        if cur.fetchone()[0] is None:
            pytest.skip("portal migration not applied (npx supabase db reset)")
    conn.rollback()
    yield conn
    conn.close()


@pytest.fixture
def db(portal_connection):
    """A connection in a transaction that is always rolled back."""
    yield portal_connection
    portal_connection.rollback()


def run(db, sql, params=None):
    with db.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else []


def become(db, user_id):
    """Act as the signed-in user `user_id` (None: logged out) until the transaction ends."""
    if user_id is None:
        run(db, "set local role anon")
        return
    run(db, "set local role authenticated")
    claims = json.dumps({"sub": str(user_id), "role": "authenticated"})
    run(db, "select set_config('request.jwt.claims', %s, true)", (claims,))


def become_admin(db):
    run(db, "reset role")


def make_user(db):
    user_id = uuid.uuid4()
    run(db, "insert into auth.users (id, email, aud, role) values (%s, %s, 'authenticated', 'authenticated')",
        (user_id, f"{user_id}@example.test"))
    return user_id


@pytest.fixture
def world(db):
    """Two clients with a user each, and one snapshot, permission and request per client."""
    ids = {}
    for name in ("a", "b"):
        client = run(db, "insert into portal_client (display_name) values (%s) returning id", (f"Client {name}",))[0][0]
        user = make_user(db)
        run(db, "insert into portal_membership (user_id, client_id) values (%s, %s)", (user, client))
        run(db, "insert into published_snapshot (client_id, kind, payload) values (%s, 'audit', %s)",
            (client, json.dumps({"owner": name})))
        run(db, "insert into client_permission (client_id, feature, status) values (%s, 'research', 'requested')", (client,))
        run(db, "insert into service_request (client_id, type) values (%s, 'research')", (client,))
        ids[name] = {"client": client, "user": user}
    ids["stranger"] = {"user": make_user(db)}  # signed up, belongs to no client
    return ids


def rejected(db, sql, params=None):
    """True if the statement is refused (RLS violation or missing privilege), leaving the transaction usable."""
    run(db, "savepoint attempt")
    try:
        run(db, sql, params)
    except (errors.InsufficientPrivilege, errors.CheckViolation):
        run(db, "rollback to savepoint attempt")
        return True
    run(db, "rollback to savepoint attempt")
    return False


def affected(db, sql, params=None):
    """Rows changed by an UPDATE/DELETE (RLS hides other rows instead of raising an error)."""
    with db.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


# ── reading ─────────────────────────────────────────────────────────────────


def test_a_client_reads_its_own_snapshot_and_nobody_elses(db, world):
    become(db, world["a"]["user"])

    rows = run(db, "select client_id, payload->>'owner' from published_snapshot")

    assert rows == [(world["a"]["client"], "a")]
    assert run(db, "select * from published_snapshot where client_id = %s", (world["b"]["client"],)) == []


@pytest.mark.parametrize("table", [
    "portal_client", "portal_membership", "published_snapshot", "service_request", "client_permission",
])
def test_every_table_shows_a_client_only_its_own_rows(db, world, table):
    become(db, world["a"]["user"])

    count = run(db, f"select count(*) from {table}")[0][0]  # noqa: S608 - fixed names from the parametrize list

    assert count == 1


def test_logged_out_visitors_read_nothing(db, world):
    become(db, None)

    assert rejected(db, "select * from published_snapshot")  # anon has no privileges at all
    assert rejected(db, "select * from portal_client")


def test_a_user_with_no_membership_reads_nothing(db, world):
    become(db, world["stranger"]["user"])

    for table in ("portal_client", "published_snapshot", "service_request", "client_permission", "upload_inbox"):
        assert run(db, f"select count(*) from {table}")[0][0] == 0, table  # noqa: S608


def test_membership_cannot_be_used_to_list_other_users(db, world):
    become(db, world["a"]["user"])

    assert run(db, "select user_id from portal_membership") == [(world["a"]["user"],)]


# ── things a client must never write ────────────────────────────────────────


def test_a_client_cannot_write_snapshots(db, world):
    become(db, world["a"]["user"])
    own, other = world["a"]["client"], world["b"]["client"]

    assert rejected(db, "insert into published_snapshot (client_id, kind, payload) values (%s, 'dashboard', '{}')", (own,))
    assert rejected(db, "update published_snapshot set payload = '{}'")
    assert rejected(db, "delete from published_snapshot")
    assert rejected(db, "insert into published_snapshot (client_id, kind, payload) values (%s, 'dashboard', '{}')", (other,))


def test_a_client_cannot_grant_itself_a_permission(db, world):
    become(db, world["a"]["user"])

    assert rejected(db, "update client_permission set status = 'granted'")
    assert rejected(db, "insert into client_permission (client_id, feature, status) values (%s, 'x', 'granted')",
                    (world["a"]["client"],))
    assert rejected(db, "delete from client_permission")


def test_a_client_cannot_join_itself_to_another_client(db, world):
    become(db, world["a"]["user"])

    assert rejected(db, "insert into portal_membership (user_id, client_id) values (%s, %s)",
                    (world["a"]["user"], world["b"]["client"]))
    assert rejected(db, "update portal_membership set role = 'admin'")
    assert rejected(db, "insert into portal_client (display_name) values ('mine now')")


# ── things a client may do, only for itself ─────────────────────────────────


def test_a_client_can_create_a_request_for_itself_but_not_for_another(db, world):
    become(db, world["a"]["user"])

    run(db, "insert into service_request (client_id, type, note) values (%s, 'new_dashboard', 'please')",
        (world["a"]["client"],))

    assert rejected(db, "insert into service_request (client_id, type) values (%s, 'research')", (world["b"]["client"],))
    assert run(db, "select count(*) from service_request")[0][0] == 2


def test_a_client_cannot_decide_its_own_request(db, world):
    become(db, world["a"]["user"])

    assert rejected(db, "insert into service_request (client_id, type, status) values (%s, 'research', 'approved')",
                    (world["a"]["client"],))
    assert rejected(db, "update service_request set status = 'approved'")
    assert rejected(db, "delete from service_request")


def test_preferences_are_per_client(db, world):
    become(db, world["a"]["user"])
    run(db, "insert into dashboard_preference (client_id, focus) values (%s, '{\"focus\": [\"retention\"]}')",
        (world["a"]["client"],))

    assert rejected(db, "insert into dashboard_preference (client_id) values (%s)", (world["b"]["client"],))
    assert affected(db, "update dashboard_preference set focus = '{}'") == 1
    assert rejected(db, "update dashboard_preference set client_id = %s", (world["b"]["client"],))
    assert rejected(db, "insert into dashboard_preference (client_id, focus) values (%s, %s)",
                    (world["a"]["client"], json.dumps({"x": "y" * 9000})))  # size cap, no need to be conflicted first


def test_upload_inbox_rows_must_be_the_clients_own_and_pending(db, world):
    become(db, world["a"]["user"])
    own, other = world["a"]["client"], world["b"]["client"]
    sql = ("insert into upload_inbox (client_id, storage_path, original_filename, size_bytes, sha256) "
           "values (%s, %s, 'export.csv', 1000, %s)")

    run(db, sql, (own, f"{own}/export.csv", SHA))

    assert rejected(db, sql, (other, f"{other}/export.csv", SHA))  # another client's id
    assert rejected(db, sql, (own, f"{other}/export.csv", SHA))  # pointing into another client's folder
    assert rejected(db, "insert into upload_inbox (client_id, storage_path, original_filename, size_bytes, sha256, status) "
                        "values (%s, %s, 'x.csv', 10, %s, 'pulled')", (own, f"{own}/x.csv", SHA))
    assert rejected(db, sql.replace("1000", "9999999"), (own, f"{own}/big.csv", SHA))  # over 5 MB
    assert rejected(db, "update upload_inbox set status = 'pulled'")
    assert rejected(db, "delete from upload_inbox")


def test_a_client_cannot_write_the_result_the_admin_reports_back(db, world):
    become(db, world["a"]["user"])
    own = world["a"]["client"]
    sql = ("insert into upload_inbox (client_id, storage_path, original_filename, size_bytes, sha256, {col}) "
           "values (%s, %s, 'x.csv', 10, %s, {val})")

    assert rejected(db, sql.format(col="message", val="'Imported 999 videos.'"), (own, f"{own}/x.csv", SHA))
    assert rejected(db, sql.format(col="status", val="'rejected'"), (own, f"{own}/x.csv", SHA))
    assert rejected(db, "update upload_inbox set message = 'all good'")


def test_the_admin_side_can_report_a_result_and_the_client_can_read_it(db, world):
    own = world["a"]["client"]
    become_admin(db)
    run(db, "insert into upload_inbox (client_id, storage_path, original_filename, size_bytes, sha256) "
            "values (%s, %s, 'x.csv', 10, %s)", (own, f"{own}/x.csv", SHA))
    run(db, "update upload_inbox set status = 'rejected', message = 'Unrecognised export' where client_id = %s", (own,))
    become(db, world["a"]["user"])

    assert run(db, "select status, message from upload_inbox") == [("rejected", "Unrecognised export")]
    become_admin(db)
    assert rejected(db, "update upload_inbox set status = 'imported'")  # only the three known statuses exist
    assert rejected(db, "update upload_inbox set message = %s", ("x" * 301,))  # the message is capped


# ── the file bucket ─────────────────────────────────────────────────────────

OBJECT = ("insert into storage.objects (bucket_id, name, owner, metadata) values ('inbox', %s, %s, '{}')")


def test_files_can_be_added_only_under_the_clients_own_folder(db, world):
    become(db, world["a"]["user"])
    own, other = world["a"]["client"], world["b"]["client"]

    run(db, OBJECT, (f"{own}/export.csv", world["a"]["user"]))

    assert rejected(db, OBJECT, (f"{other}/export.csv", world["a"]["user"]))
    assert rejected(db, OBJECT, ("export.csv", world["a"]["user"]))  # no folder at all
    assert rejected(db, OBJECT, (f"{own}/../{other}/x.csv", world["a"]["user"]))  # traversal attempt


def test_a_client_cannot_list_read_overwrite_or_delete_files(db, world):
    become_admin(db)
    run(db, OBJECT, (f"{world['b']['client']}/secret.csv", None))
    run(db, OBJECT, (f"{world['a']['client']}/mine.csv", None))
    become(db, world["a"]["user"])

    assert run(db, "select count(*) from storage.objects where bucket_id = 'inbox'")[0][0] == 0  # not even its own
    assert affected(db, "update storage.objects set name = name || 'x' where bucket_id = 'inbox'") == 0
    # Deleting is refused by Supabase's own storage trigger, and would match no visible row anyway.
    assert rejected(db, "delete from storage.objects where bucket_id = 'inbox'")


def test_the_bucket_is_private_and_capped(db, world):
    become_admin(db)

    public, limit, types = run(
        db, "select public, file_size_limit, allowed_mime_types from storage.buckets where id = 'inbox'")[0]

    assert public is False and limit == 5 * 1024 * 1024 and len(types) == 3


# ── the service key still works (the admin app's path) ──────────────────────


def test_the_admin_side_can_publish(db, world):
    become_admin(db)  # stands in for the service key, which bypasses row-level security

    run(db, "insert into published_snapshot (client_id, kind, payload) values (%s, 'dashboard', '{}')",
        (world["a"]["client"],))
    run(db, "update published_snapshot set payload = '{\"v\": 2}' where client_id = %s and kind = 'dashboard'",
        (world["a"]["client"],))
    become(db, world["a"]["user"])

    assert run(db, "select payload->>'v' from published_snapshot where kind = 'dashboard'") == [("2",)]


def test_deleting_a_client_removes_everything_it_owns(db, world):
    become_admin(db)

    run(db, "delete from portal_client where id = %s", (world["a"]["client"],))

    for table in ("portal_membership", "published_snapshot", "service_request", "client_permission"):
        assert run(db, f"select count(*) from {table} where client_id = %s", (world["a"]["client"],))[0][0] == 0  # noqa: S608
