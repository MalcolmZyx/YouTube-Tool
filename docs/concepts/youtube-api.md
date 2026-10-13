# The YouTube Data API: what we use it for, and the structure around it

Code: [`apps/api/youtube/`](../../apps/api/youtube/). This is the **structure**; the deeper work (quota accounting,
comments, the Analytics API) comes later.

## What it is used for

Public, read-only details for videos that are already in a client's export: **description, tags, category,
thumbnail**. The Studio export has the numbers (views, CTR, ...) but none of these. They feed the Keywords and
Descriptions pages and the thumbnails. Nothing is written to YouTube, no OAuth, only an API key.

The Researcher page also uses it (`search.list`) for competitor tags; that data is shown, not stored.

## The structure

| Piece | File | Job |
|---|---|---|
| Fetcher | `youtube/client.py` | `videos.list`, 50 IDs per request (1 quota unit each); quota and key errors are told apart; the key never appears in an error message |
| Store | `youtube/store.py` | saves details with `expires_at = now + 30 days`; refreshes data older than 7 days; hides expired data |
| Purge | `python -m youtube purge` | deletes what was not renewed within 30 days; meant to run daily |
| Route | `POST /api/clients/{id}/enrich` | fetch what is missing or stale (429 on quota, 502 on other API failures) |
| Command | `python -m youtube refresh <client_id>` | the same from the terminal |

## Rules it follows (YouTube Developer Policies)

* **Public data is kept at most 30 days** (III.E.4.d): `expires_at` on every row; analyses ignore expired rows even
  if the purge has not run yet; the weekly refresh renews data long before it lapses.
* **Delete on request within 7 days** (III.E.4.g): deleting a client erases its API data in the same transaction
  (foreign-key cascade), so it is immediate.
* **No cross-channel aggregation** of API data (III.E.2): nothing here compares clients.
* **Credentials** (III.D.1): one key for this one app, read from `.env`, never committed, never logged.

## Not decided yet (so not built)

* The exact wording of **III.E.4.h** (derived metrics): keyword scores are computed from API tags. To be read in full
  and settled before this goes beyond private use.
* **Quota accounting** per client and a daily budget; **scheduling** the purge (Task Scheduler or cron, Phase 5).
* **Clients using their own API key**: judged a poor fit for the credential rules; alternatives are a per-client quota
  on our key, or OAuth "connect my channel" for private data.
* **Comments** (`commentThreads.list`) and how long their text may be kept.

## You should be able to explain

1. Which data comes from the export and which from the API, and why the API is needed at all.
2. Why 50 IDs per request, and what a private video looks like in the response.
3. What happens to API data after 30 days, and what three things make sure of it?
4. Why must an error message never include the request URL?
5. Why is a client's own API key a problem for a shared app?
