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
| Store | `youtube/store.py` | MongoDB: one document per client and video holding the raw API snippet; `expires_at = fetched_at + 30 days`; refreshes data older than 7 days; hides expired data |
| Retention | TTL index `expires_at` | MongoDB deletes each document itself when it expires: the 30-day rule is the database's job, not a job we must remember to run |
| Purge | `python -m youtube purge` | deletes expired documents right now (the database also does it within about a minute) |
| Route | `POST /api/clients/{id}/enrich` | fetch what is missing or stale (429 on quota, 502 on other API failures) |
| Command | `python -m youtube refresh <client_id>` | the same from the terminal |

## Why MongoDB holds this (and Postgres the rest)

* **Different lifetime.** The creator's export is kept as long as the relationship lasts. Public API data must be gone
  within 30 days. A TTL index (`expireAfterSeconds: 0` on `expires_at`) makes MongoDB delete each document the moment
  that time passes, so the rule holds even if nobody ever looks at an alert. Verified for real: an expired test
  document disappeared by itself after 15 seconds (the TTL monitor runs about once a minute).
* **Different shape.** What is stored is exactly the snippet YouTube returned, whatever fields it has. The fields the app
  uses (description, tags, thumbnail) are derived when read, so a new use of the same data needs no new fetch and no
  schema change.
* **Honest limits.** Reads still ignore a document past its expiry, because the TTL monitor is not instant. There is no
  foreign key between the stores, so deleting a client deletes its documents explicitly and refuses to proceed if
  MongoDB cannot be reached (otherwise a copy could be left behind, against YouTube's delete-on-request rule).
* **Optional at runtime.** With no `MONGO_URL` the YouTube features say they are not configured; the dashboard, audit
  and portal work as before.

## Quota: what is left today

YouTube's API **does not tell us** the remaining quota, so the app counts what it spends (`youtube/quota.py`, table
`api_usage`) and the sidebar shows it: `7,699 of 10,000 units left`, a bar, and the time until the reset.

* **The period is one day**, and YouTube's day is **Pacific time**, resetting at midnight there. Postgres works that out
  (it knows the time-zone rules), so it is right across daylight-saving changes.
* **Costs counted:** a batch of up to 50 videos is 1 unit; a Researcher search is in its own bucket of 100 calls a day since 2026-06-01 (not counted here), plus 1 for its details call.
* **It is an estimate.** It cannot see other uses of the same key (another script, the Google console's own tests), so
  the hover text says so. If YouTube ever answers "quota exceeded", today's count is set to the full limit, so the meter
  agrees with reality and no more calls are made until the reset.
* **Before fetching,** the app compares the cost with what is left and refuses with a clear message instead of failing
  halfway. The limit is `YOUTUBE_DAILY_QUOTA` in `.env` (default 10,000) in case Google raises it.
* The hover text also shows the last 7 days of use.

## Stored data that needs attention (manual for now)

Refreshing and deleting are **manual** until the automation phase, so the app tells you when to act. A banner at the top
of every page appears for any client whose stored YouTube data

* **expires within 7 days** (amber), which is the useful one: data silently disappearing at 30 days would leave
  Keywords and Descriptions empty, so the week's warning is the chance to refresh it. MongoDB deletes expired data
  within about a minute, so the red "expired" state is rarely seen.

The banner has **Refresh now** (fetches again and renews the 30 days) and **Delete YouTube data** (erases that client's
tags, descriptions and thumbnails after a confirmation; the exported figures stay). Routes: `GET /api/public-data/alerts`,
`POST /api/clients/{id}/enrich`, `DELETE /api/clients/{id}/public-data`. `python -m youtube purge` still exists for
deleting everything expired at once.

## Rules it follows (YouTube Developer Policies)

* **Public data is kept at most 30 days** (III.E.4.d): a TTL index on `expires_at` makes MongoDB delete it; analyses
  ignore expired documents even before it does; the weekly refresh renews data long before it lapses.
* **Delete on request within 7 days** (III.E.4.g): deleting a client erases its documents at once (explicitly, since
  the stores are separate) and refuses to delete if MongoDB cannot be reached.
* **No cross-channel aggregation** of API data (III.E.2): nothing here compares clients.
* **Credentials** (III.D.1): one key for this one app, read from `.env`, never committed, never logged.

## Not decided yet (so not built)

* The exact wording of **III.E.4.h** (derived metrics): keyword scores are computed from API tags. To be read in full
  and settled before this goes beyond private use.
* A **per-client** quota budget (the meter is for the whole key); **scheduling** the refresh (Task Scheduler or cron, Phase 5). Deleting is already automatic.
* **Clients using their own API key**: judged a poor fit for the credential rules; alternatives are a per-client quota
  on our key, or OAuth "connect my channel" for private data.
* **Comments** (`commentThreads.list`) and how long their text may be kept.

## You should be able to explain

1. Which data comes from the export and which from the API, and why the API is needed at all.
2. Why 50 IDs per request, and what a private video looks like in the response.
3. What happens to API data after 30 days, and what three things make sure of it?
4. Why must an error message never include the request URL?
5. Why is a client's own API key a problem for a shared app?
6. The API does not report remaining quota. How do we know what is left, and why is it only an estimate?
7. Why is the quota day computed in the database, in Pacific time?
8. Why is the raw API data in MongoDB with a TTL index instead of Postgres tables? What does that guarantee, and what does it not?
