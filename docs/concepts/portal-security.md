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
