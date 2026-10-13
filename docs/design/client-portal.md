# Client portal: design (draft, before any code)

Status: agreed direction (publish snapshots, Supabase, local first). Open points are listed at the end.

## What it is

Two apps, and the line between them is the point:

```
 YOUR MACHINE (admin app, exists today)                     HOSTED (portal)
 ┌──────────────────────────────────────┐   Publish ──►  ┌──────────────────────────────┐
 │ raw exports · all clients · API key  │                │ Supabase: Auth + Postgres    │
 │ importer · audit engine · reports    │  ◄── Pull ───  │  - published snapshots       │
 └──────────────────────────────────────┘  (uploads,     │  - requests, permissions     │
                                            requests)    │  - upload inbox (temporary)  │
                                                         └──────────────┬───────────────┘
                                                                        │ RLS: a client sees only their rows
                                                                 portal web app (React)
```

* **The admin app never goes online.** The portal never holds raw exports, other clients' data, or your YouTube key.
* **Publish** copies finished products for one client (the audit findings and the dashboard table) into the portal
  database. The client sees a **snapshot** until you publish again.
* **Pull** goes the other way: you fetch what clients created (uploaded exports, requests) into the admin app, then
  delete it from the portal. Nothing is pushed into your machine; your machine reaches out.

## Why Supabase

Login and Postgres in one product, and its login is wired into Postgres row-level security: the signed-in user's id is
available inside the database as `auth.uid()`. Free tier (as of the research, to re-check before relying on it): 50,000
monthly active users, 500 MB database, 2 active projects, and **a free project pauses after a week of inactivity**
(data kept, site down until restored). The whole stack also runs locally in Docker (`supabase start`), so we build and
test with no account and no cost, and deployment is a later step.

## Tables (portal database)

All have row-level security **on**, and no policy means no access.

| Table | Holds | Client may |
|---|---|---|
| `portal_client` | id, display name | read their own |
| `portal_membership` | `user_id` → `client_id`, role (`client` or `admin`) | read their own row |
| `published_snapshot` | `client_id`, `kind` (`audit` / `dashboard`), `payload` (JSON), `as_of`, `published_at` | **read** their own; never write |
| `service_request` | `client_id`, `type` (e.g. new dashboard, research), `note`, `status` (requested, approved, declined, done) | create and read their own |
| `client_permission` | `client_id`, `feature`, `status`, `quota`, `expires_at` | read their own; never write |
| `dashboard_preference` | `client_id`, focus areas (JSON) | read and update their own |
| `upload_inbox` | `client_id`, file path, name, size, SHA-256, status (pending, pulled) | create and read their own |

Files live in a storage bucket `inbox`, path `<client_id>/<file>`; a client may add files only under their own
`client_id`, and cannot read or overwrite what is there.

**The rule for every client-facing policy** is the same one line: the row's `client_id` must be among the clients the
signed-in user belongs to (`portal_membership`). Everything the client cannot write (snapshots, permissions) is written
only by the admin app using the **service key**, which exists only in the admin app's `.env` and is never in the portal's
code or the browser.

## Flows

1. **Publish.** In the admin app: *Publish to portal* for a client → writes `published_snapshot` rows (audit JSON and
   dashboard table). *Unpublish* deletes them. Deleting a client locally also unpublishes.
2. **Client uploads an export.** Portal → storage inbox (size and type checked) → `upload_inbox` row. Admin app *Pull
   inbox* downloads each file, runs it through the same `spool_upload` and `import_export` rules as any upload, then marks it
   pulled and deletes the stored copy. The raw file is online only until you pull it.
3. **Client asks for something.** A button creates a `service_request`. The admin app shows a per-client inbox; you
   approve, run the work, publish, and set the status, which the client sees.
4. **More access.** Everything beyond "view my published dashboards, upload, set focus" is a permission request you grant in
   the admin app (feature, quota, expiry). The portal checks permissions on every call, server-side.

## What is deliberately not published

* **No YouTube API data in version 1** (tags, descriptions, thumbnails). It has a 30-day limit and must be refreshed or
  deleted; the snapshot would need the same expiry. We publish only what comes from the creator's own export and the audit
  computed from it, and add API data later with an expiry.
* **No client-supplied API keys.** Decided earlier: poor fit for YouTube's credential rules.

## How we prove the isolation (the tests matter more than the policies)

Tests run against the local Supabase database and act as a signed-in user (`set local role authenticated` plus the user's
id in the JWT claims, the standard way to simulate a login in SQL). They must show:

* client A reads A's snapshot; client A reading B's snapshot returns **zero rows**;
* a client cannot insert, update or delete a snapshot or permission;
* a client cannot add a request or an inbox row for another `client_id`;
* a logged-out user reads nothing;
* a user with no membership reads nothing.

A policy nobody tried to break is not evidence of anything.

## Build order

1. Portal schema, RLS and the isolation tests, on local Supabase. *(the part that must be right)*
2. Publish and unpublish from the admin app.
3. Portal web app: sign in, view the published dashboard and audit.
4. Requests, permissions and dashboard preferences.
5. Client uploads: inbox bucket, pull, import.

## Open points

* **Invites.** Invite-only sign-up (you create the user and membership), no public sign-up page.
* **Where the portal app lives:** a new `apps/portal` React app (shares components with `apps/web`) is the plan.
* **Snapshot history:** keep the latest per kind, or every version? Latest only is simpler; versions help "what changed
  since last audit".
* **Notifications** when you publish or a request changes status (email later).
* **Audit log** of who viewed what, wanted for the compliance story; not in the first slice.
* **Privacy policy and terms** for a site that holds other people's data: needed before real clients, outside the code.
