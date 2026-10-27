# Collecting comments for a classifier: a balanced corpus

Code: [`apps/api/youtube/`](../../apps/api/youtube/) (`text.py`, `strata.py`, `discovery.py`, `enrich.py`,
`comments.py`, `comment_store.py`, `crawler.py`). Commands: `python -m youtube crawl`, `python -m youtube coverage`.

## What it is for

A classifier for "constructive criticism" in comments (text only, English only). The corpus is **research data, not tied
to any client**: public comments of public videos, used for training and serving a model. The owner has the YouTube
team's go-ahead for that use. The comments are labelled by hand later.

## Why balanced strata

Search and trending lists return big channels first, so a corpus built from "whatever comes back" is influencer
comments, and a model trained on it fails on a 300-view tutorial. So every crawled video is placed in a **cell**:

| Axis | Bands (lower bound inclusive) |
|---|---|
| category | the 15 assignable `videoCategoryId`s (Gaming, Education, Music, ...) |
| view count | `<1k`, `1k-10k`, `10k-100k`, `100k-1M`, `1M+` |
| subscribers | the same five, plus `hidden` (the channel hides its count) |
| age at crawl time | `<1mo` (under 30 days), `1mo-6mo` (under 183), `6mo-1y`, `1y-3y` (under 1,095), `3y+` |

`python -m youtube coverage` prints videos, comments and share per value on each axis, and the emptiest category x age
pairs. The scheduler (`strata.next_targets`) picks the pair with the fewest kept comments, ties broken by a seeded RNG,
so a run is repeatable. Only category and age can be asked of the API directly; view and subscriber bands are an
outcome, so they are measured and steered indirectly (below), not guaranteed. The report is how you see the gap.

## How low-audience videos are found

* **Short random windows.** `search.list` with `type=video`, `order=date`, `videoCategoryId`, `relevanceLanguage=en` and
  `publishedAfter`/`publishedBefore` set to a two-hour window placed at random inside the chosen age band. In a window
  that short almost every upload is from a small channel, simply because there are far more of them.
* **View count order for the other end.** For bands older than a month, when fewer than 40% of that band's videos have
  100k+ views, the search uses `order=viewCount` over a 72-hour window, which surfaces the well-viewed videos date order
  never returns.
* **Charts.** One round in ten reads `videos.list chart=mostPopular` for the category (current popular videos).
* **Uploads.** When the search bucket is used up, the latest uploads of channels already seen are read from the
  channel's own uploads playlist (the ID comes from `channels.list contentDetails.relatedPlaylists.uploads`).
* A category that refuses a filter or has no chart answers with an error. That is logged and skipped; the run goes on.

## The filters

Applied in `youtube/text.py`, **the one cleaning function training and inference must share** (pure: text in, text out).

1. **Video level** (`enrich.py`): drop made-for-kids videos, videos without a `commentCount` (comments disabled or
   hidden) and videos under `--min-comments` (default 3). Comments disabled found at read time (403 `commentsDisabled`)
   is recorded as skipped.
2. **Cleaning:** `@handles` become `@user`, URLs become `<url>`, whitespace collapses.
3. **Substantial:** at least 3 words (runs of letters; digits and emoji are not words) after removing mentions, URLs and
   timestamps. Empty, emoji-only, `3:20`-only and "lol" are dropped.
4. **Duplicates:** the text is normalised (case, punctuation, emoji, spacing) and fingerprinted; the first copy wins,
   across the whole corpus (an indexed `dedupe_key` field), because copy-paste spam is common.
5. **English:** `langdetect` (pure Python, seed 0 so the answer never changes), kept when P(en) >= 0.8.
6. **Sample:** the survivors of up to `--max-pages` pages (newest first, 100 threads a page) are sampled at random down to
   `--per-video-cap` (default 25), so no video dominates. `sampling` records e.g. `time_pages_2`.

Everything dropped is counted by reason in the summary (`insubstantial`, `not_english`, `duplicate`, `over_cap`,
`made_for_kids`, `comments_disabled`, `few_comments`, `unavailable`), not stored.

**Privacy:** only text and counts are kept. No author name, picture or channel URL. The author's channel ID is stored only
as `sha256(salt + id)` and only when `COMMENT_AUTHOR_SALT` is set; with no salt the field is null.

## Storage, quota and the 30-day rule

* MongoDB collections `youtube_comment` and `youtube_crawl_video`, each with a TTL index on `expires_at`
  (`fetched_at + 30 days`), like the rest of the public YouTube data: re-crawl to renew, otherwise the database deletes it.
  Labels must therefore be copied out of this store into their own (to be decided in the labeling phase) before
  they can outlive a comment.
* One field beyond the agreed contract: `dedupe_key` on comments (for the cross-run duplicate check).
* Quota (per the official `determine_quota_cost` page): `videos`, `channels`, `playlistItems` and `commentThreads` are
  1 unit each from the 10,000 main pool. `search.list` has had **its own bucket, 100 calls a day, since 2026-06-01**, so
  it no longer costs 100 main units. A round is 1 search, 2 setup calls and 1-2 comment pages per video: about 30 to 80
  main units for 25 videos. The search bucket is the limit: about 2,500 videos a day at best.
* After each run `quota.record` gets the main-pool units; searches are not recorded in `api_usage` (see below).

## Verified and not verified

Checked against developers.google.com/youtube/v3 on 2026-10-26: parameter names and ranges of `search.list`,
`commentThreads.list`, `videos.list`, `channels.list`, `playlistItems.list`; costs; the 2026-06-01 bucket change; error
reasons `commentsDisabled` (403), `videoNotFound` (404), `videoChartNotFound` (400); resource properties of
videos, channels, commentThreads and comments; `textOriginal` is visible only to the author, hence `textDisplay` with
`textFormat=plainText`.

Not verified (no API key, so no live call was made): the revision history says only "its own bucket" for search, the
number 100 calls a day is from the method page (confirm in the Cloud Console); the 50-ID limit of `videos.list` and
`channels.list` is not stated on their method pages (it is the existing `client.py` assumption); what `commentCount` is
when comments are disabled (an absent field is treated as disabled); which categories reject which search filters;
`playlistItems` response fields beyond `snippet.resourceId.videoId`. The daily count of search calls is **not
persisted**: each run may use up to 100 searches, and when the API refuses a search the run carries on with charts and
uploads.

## You should be able to explain

1. Why a corpus from the first search results would fail on small channels, and how the strata prevent that.
2. How a two-hour `publishedAfter`/`publishedBefore` window finds small channels, and why view count order needs a wider one.
3. Why `view_band` and `subscriber_band` cannot be requested from the API, and how the crawler still steers them.
4. Why cleaning must be one shared function, and what goes wrong if training and serving clean differently.
5. Why the language check runs on text without mentions and URLs, and why 0.8.
6. Why duplicates are removed across the whole corpus and not per video. What would the model learn from spam?
7. Why sample 25 of the filtered comments at random instead of taking the first 25.
8. What `search.list` costs now, what limits a crawl, and why the main meter does not move for searches.
9. Why the author is hashed with a salt, and why no salt means no identifier at all.
10. What the TTL index guarantees, and why labels cannot live only in this collection.
11. Why a category that rejects a filter is skipped and a quota error is not.
