# Portal security: row-level security and how we test it

Code: [`supabase/migrations/`](../../supabase/migrations/), tests: [`apps/api/tests/test_portal_rls.py`](../../apps/api/tests/test_portal_rls.py).
Design and flows: [../design/client-portal.md](../design/client-portal.md).

## The problem

A hosted portal holds many clients' data in one database. The danger is not a clever attacker; it is one forgotten
`where client_id = ...` in one query, which shows client A client B's numbers. Checking in application code means every
query must remember. **Row-level security (RLS)** moves the rule into the database, so a query that forgets still
cannot see other clients' rows.

## How it works here

1. **Login** is Supabase Auth. A signed-in request carries a token; inside Postgres the user's id is `auth.uid()`.
2. **Membership** (`portal_membership`) says which client a user belongs to.
3. **One rule for every client-facing table:** the row's `client_id` must be one of the caller's clients
   (`public.my_client_ids()`). That function is `security definer`: it runs with the table owner's rights so that the rule
   can read the membership table without the membership table's own policy recursing into itself.
4. **Reading and writing are separate permissions.** A client can read its snapshots and permissions but there is no
   write policy at all, so any write is refused. Only the admin app writes them, using the **service key**, which bypasses
   RLS and therefore exists only in the admin app's environment, never in the portal's code or browser.

## Two layers, on purpose

* **Privileges** (`grant`/`revoke`): Supabase hands new tables to the `anon` and `authenticated` roles by default. The
  migration revokes that and grants back only what is used, down to columns (a client may insert `client_id, type, note`
  into a request but not its `status`).
* **Policies** (RLS): which rows those privileges apply to.

Either alone would be enough for the cases we thought of; together a mistake in one is caught by the other.

## Invite-only

Public sign-up is turned off with `[auth] enable_signup = false`. You create the user and their membership; there is no
sign-up page to attack and no stranger can create an account that then sits in the same database.

**A trap this caught:** `[auth.email] enable_signup` looks like the same switch but is not. It switches the *email
provider* on or off, so setting it to false made every login fail ("Email logins are disabled"). Only a test that logged
in over real HTTP found it; the SQL-level tests could not, because they simulate the login. It must stay `true`.

## The file inbox

Clients upload exports to a private bucket. A policy lets them add files only under their own `<client_id>/` folder and
refuses names with `..` segments; there is **no** read, list, overwrite or delete policy, so a client cannot fetch
another client's file or even its own after uploading. The bucket also caps size (5 MB) and type (`.csv`, `.xlsx`). The
inbox row's `storage_path` must start with the client's own id (a `check` constraint).

## How we prove it: tests that attack

A policy nobody tried to break is not evidence. The tests sign in as users (`set local role authenticated` and the user's
id in the JWT claims, the standard way to simulate a login in SQL) and attempt what a hostile client would:

* read another client's snapshot, request, permission or membership (zero rows);
* write, edit or delete a snapshot or grant itself a permission;
* add a request or inbox row for another client, set its own request to "approved", point an upload at another folder;
* upload with a `../` path, read or delete files, join itself to another client;
* browse as a logged-out visitor, or as a user who belongs to no client.

They also check the admin path still works (publishing) and that deleting a client removes everything it owns. Tests run in a
transaction that is rolled back, against the local Supabase stack, and are skipped when it is not running (`REQUIRE_PORTAL_DB=1`
makes a missing stack a failure instead).

## End-to-end check (real logins over HTTP)

The SQL tests simulate a login. The check that matters most is the real path: the admin API publishes two clients to
the local portal, two real users are created and sign in through the auth service, and each then reads the portal's REST
API with their own token. Verified: a user sees exactly their own two snapshots; asking for the other client's returns
nothing; writing or editing a snapshot is refused (403); a request for themselves is accepted (201) and for the other
client refused; a visitor with no login is refused (401); public sign-up is refused; and after unpublishing the portal
holds nothing. Only the *admin API's* publish path uses the service key.

## Requests, access and focus

Who may change what, and why it is built this way:

| Thing | Client | Admin app (service key) |
|---|---|---|
| Request (`service_request`) | create for itself, read its own | read all, set the status |
| Access (`client_permission`) | read its own | grant, deny, set a quota and an expiry, remove |
| Focus (`dashboard_preference`) | read, create, change its own | read |

* **A client can never decide its own request or grant itself access**: there is no update privilege on those columns at
  all (a request's `status` is not even insertable), so the database refuses it, whatever the portal code does.
* **The admin app reaches out.** Nothing is pushed into your machine: the Requests page reads the portal on demand, and a
  badge in the sidebar counts requests still waiting. Acting on one writes its new status back, which the client sees.
* **Notes are untrusted text.** A client's note is stored and shown as plain text in both apps (React escapes it). The
  test submits `<b onmouseover=alert(1)>` and checks nothing was injected. Notes are capped at 1,000 characters by the
  database and the focus choices at 8 KB.
* **Focus is stored, not yet acted on.** It tells you what the client cares about; letting it steer the audit is later work.
* The admin routes validate before anything is sent: only the four statuses, a `[a-z0-9_]` feature name, a non-negative quota.

Checked end to end with real logins in a browser: the client asked, the admin approved and granted access with a quota, the
client saw both; client B saw none of A's requests or choices; A could not change a status, grant itself access or write B's
preferences (403); an oversized note was refused.

## What this does not cover (yet)

* The service key is the master key: its safety is operational (never in the browser, never committed).
* Rate limiting and abuse of the login endpoint (Supabase has built-in limits; check them at deployment).
* The local stack has no TLS and default credentials. It is for development only.
* An audit log of who viewed what.

## You should be able to explain

1. What goes wrong with checking `client_id` in application code, and how does RLS change that?
2. What does `auth.uid()` return, and where does the value come from?
3. Why is `my_client_ids()` a `security definer` function, and what would happen without it?
4. Why can a client read its snapshot but not change it, and who can?
5. Why revoke the default privileges as well as writing policies?
6. Why turn off public sign-up for an invite-only portal?
7. Which attacks do the tests attempt, and why is a test that tries to break the policy better than reading the policy?

## The portal app (browser-level check)

`apps/portal` holds only the public anon key and the user's own session; it has no route to the admin app and no secret.
Driving it in a real browser (headless Chrome) verified: a visitor sees only the sign-in form; a wrong password gives one
generic message (the same for an unknown address, so it does not reveal which accounts exist); after signing in the user
sees their client's 60 videos and totals and never the other client's name; the audit page shows every finding with its
caveats; nothing resembling the service key is in the browser's storage; sign-out returns to the form; no script errors.
Video titles come from creators' files, so they are only ever rendered as React text (escaped), never as HTML.

For deployment (not done yet): a Content-Security-Policy, HTTPS only, and a rate limit on sign-in attempts.
