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
pairs. The scheduler (`strata.next_targets`) picks the pair with the fewest videos (then comments), ties broken by a
seeded RNG, so a run is repeatable. Only category and age can be asked of the API directly; view and subscriber bands
are known only after `videos.list` and `channels.list`, so they are steered in two places (below). The report is how you
see the gap.

## How the corpus is kept balanced

A first live crawl of 300 videos was not balanced: about 70% of the videos had 100k+ views, about 63% of the channels had
100k+ subscribers, 55% of the comments came from videos under a month old, and Sports, News & Politics and Pets & Animals had
2 to 6 videos each. The scheduler only knew category and age band, so audience size was never steered. Three changes:

1. **Quota sampling after enrichment (`strata.over_quota`).** Once a round's candidates have their bands and before any
   `commentThreads` page is spent, each video is checked on all four axes. The target is an equal share across the bands
   of that axis that already hold a video plus the candidate's own band (and at least 3 bands, so a corpus that starts in
   one band cannot lock itself in). A video is turned away when its band would pass the target by more than 25%
   (`OVER_TARGET_SLACK`), for example more than 25% of the corpus in one of five view bands. Below 10 videos nothing is
   turned away. A band the corpus has never seen is always let in, so a rare band can start. The decision uses the
   coverage already in Mongo plus the videos taken earlier in the same round, so repeated runs keep balancing. The
   reason appears in the run summary as `over_quota_view_band`, `over_quota_subscriber_band`, `over_quota_age_band` or
   `over_quota_category_id` (the first axis that fails). Nothing here is random, so the same seed on the same corpus
   gives the same result.
2. **The emptiest view band decides how to search (`strata.next_view_band`).** Low bands (`<1k`, `1k-10k`): a small
   channel's uploads (3 rounds in 10) or a date search. Middle and high bands: `order=viewCount`. `1M+`: the chart in half
   the rounds. The uploads read comes from the channels of crawled videos whose subscriber band is `<1k` or `1k-10k`,
   taken from the store at the start of a run, so they accumulate across runs.
3. **Stopping rules.** A round with no new video counts against its (category, age band) pair, which is left alone after
   2 such rounds, and against the view band it was chasing, which is left alone after 3 in a row; a round that found a
   video in that view band resets it. After 20 empty rounds in a row the run ends as `no_new_videos`. So an axis that
   cannot be filled (no small videos in the index for that age band, no chart for a category) is not chased for ever,
   and a run whose every remaining candidate is over quota ends instead of spending comment units.

The price is yield per search. Equal shares need candidates the index rarely returns, so a balanced run keeps fewer
videos per search call than an unbalanced one, and the 100 searches a day become the limit (measured below).

## How low-audience videos are found

* **A common word in `q`.** `search.list` with `type=video`, `order=date`, `videoCategoryId`, `relevanceLanguage=en`,
  `publishedAfter`/`publishedBefore` and `q` set to one of `my`, `the` (chosen by the seeded RNG). See the measurements
  below: without a `q` the index answers with well-viewed videos.
* **A window that widens with the age band.** 2 hours (`<1mo`), 24 hours (`1mo-6mo`), 72 hours (`6mo-1y`, `1y-3y`), 168
  hours (`3y+`), placed at random inside the band. Older videos are sparse in the index, so a two-hour window is empty.
* **View count order for the high end.** `order=viewCount` over a 72-hour window, no `q`.
* **Charts.** `videos.list chart=mostPopular` for the category, only when `1M+` is the emptiest view band or search is
  closed.
* **Uploads.** The latest uploads of a channel, from its own uploads playlist (the ID comes from `channels.list
  contentDetails.relatedPlaylists.uploads`).
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
  main units for 25 videos. The search bucket is the limit: each search gives at most 50 candidates, and a balanced run
  kept about 2 videos per search in the live test below (so about 200 a day), where an unbalanced run keeps up to 25.
* After each run `quota.record` gets the main-pool units; searches are not recorded in `api_usage` (see below).

## Verified and not verified

Checked against developers.google.com/youtube/v3 on 2026-10-26: parameter names and ranges of `search.list`,
`commentThreads.list`, `videos.list`, `channels.list`, `playlistItems.list`; costs; the 2026-06-01 bucket change; error
reasons `commentsDisabled` (403), `videoNotFound` (404), `videoChartNotFound` (400); resource properties of
videos, channels, commentThreads and comments; `textOriginal` is visible only to the author, hence `textDisplay` with
`textFormat=plainText`.

Not verified: the revision history says only "its own bucket" for search, the number 100 calls a day is from the method
page (confirm in the Cloud Console); which categories reject which search filters (category 19 has no chart: 404
`notFound`, handled); `playlistItems` response fields beyond `snippet.resourceId.videoId`. The daily count of search
calls is **not persisted**: each run may use up to 100 searches, and when the API refuses a search the run carries on
with charts and uploads.

### Measured live on 2026-10-26 (owner's key, throw-away database, 40 search calls and about 380 units in all)

Each experiment is one `search.list` call of 50 results, then `videos.list` and `channels.list` for all 50. The same
window was used for the variants of one row.

| Search (cell) | Results | Under 10k views | Under 10k and 3+ comments |
|---|---|---|---|
| date, 2h, category, `relevanceLanguage=en` (Gaming, `<1mo`) | 50 | 1 | 1 |
| same, no `relevanceLanguage` | 50 | 0 | 0 |
| same, no category | 50 | 0 | 0 |
| same, `order=relevance` | 50 | 0 | 0 |
| same, `q=the` | 50 | 11 | 6 |
| same, `q=my` | 50 | 35 | 17 |
| date, 2h, `q=the` (People & Blogs, `<1mo`) | 21 | 6 | 2 |
| date, 2h, no `q` (Education, `6mo-1y`) | 4 | 1 | 0 |
| date, 2h, no `q` (People & Blogs, `3y+`) | 0 | 0 | 0 |
| date, 72h, no `q` (Education, `6mo-1y`) | 50 | 5 | 3 |
| date, 72h, `q=the` (Education, `6mo-1y`) | 50 | 10 | 2 |
| date, 168h, `q=the` (People & Blogs, `3y+`) | 50 | 5 | 2 |

What this shows:

* **The search index answers a query with no `q` with well-viewed videos.** The median view count of the two-hour
  Gaming window was 223,000, and 37 of its 50 videos had 100k+ views, although a two-hour window must hold mostly small
  uploads. A common word (`the`) makes the median 31,000. This, not the window length, is why
  `order=date` windows gave 14 videos under 10k views in 173. Why it happens is not documented: it is an observation of
  the index on one day, from one window per row, not a guarantee.
* **A two-hour window is empty for videos older than six months** (0 to 4 results), so those searches were wasted
  calls. 72 and 168 hours return 50, but mostly 100k+ videos: older small videos are rare in the index.
* In the one window with `q=my`, 17 of 50 videos were under 10k views and had 3+ comments. In the other `q` windows 2 to 6.
  The two words differ a lot in one window each; that is two samples, not a ranking.
* **Minimum comments.** Of the 76 videos under 10k views seen, 28 had no comments, 9 had one, 6 had two, 33 had three or
  more. Lowering `--min-comments` from 3 to 2 would add 6 videos (+18%), each worth at most 2 comments for 1 unit, so the
  default stays 3.
* `relevanceLanguage=en`: 30 of 50 videos tagged `en` against 21 without it, and no small-video effect either way. Kept.
* `totalResults` is useless: 1,000,000 for most windows.

Live run with the quota (seed 2, 12 searches, then 7 uploads reads): 22 videos kept, 397 comments, the run then ended as
`no_new_videos`. The first crawl's tables for comparison are from 300 videos, so the sizes differ.

| | First crawl (300 videos) | With the quota (22 videos) |
|---|---|---|
| view band `<1k` / `1k-10k` / `10k-100k` / `100k-1M` / `1M+` | 4 / 23 / 67 / 113 / 103 | 2 / 5 / 5 / 5 / 5 |
| subscriber band, same five, `hidden` | 10 / 32 / 74 / 105 / 89 / 0 | 1 / 5 / 5 / 6 / 5 / 0 |
| age band `<1mo` / `1mo-6mo` / `6mo-1y` / `1y-3y` / `3y+` | 185 / 36 / 31 / 19 / 39 | 7 / 3 / 2 / 0 / 10 |
| videos from `order=date` searches under 10k views | 14 of 173 | 7 of 15 |

View and subscriber bands came out even; age and category did not (10 of the 22 videos are Travel & Events, from one
`3y+` window that happened to hold many small videos). The run was too short for age and category to even out, and the
per-search yield was 1.25 videos from date searches: the quota rejected 726 candidates by view band and 127 by category.
**The 300-video run was not possible**: the 40 search calls allowed for this work were spent on the experiments above
(20), a first 8-search pilot (which showed that a corpus with one band per axis locked itself in, hence the 3-band
floor) and this run (12). An offline replay of the 331 candidates with 3+ comments from the experiments through the quota
accepted 10 to 22 of them with a 25% slack and 12 to 48 with 50%: the supply of small videos in other categories and age
bands, not the quota, is the limit, and a looser slack (`OVER_TARGET_SLACK`) trades balance for yield.

### What did not work, or is not shown

* No `relevanceLanguage`, no category, and `order=relevance` returned no more small videos than the baseline.
* Two-hour windows older than six months.
* Uploads of small channels: 7 reads (14 units) of channels from the corpus produced 0 kept videos, but their candidates
  were turned away by the quota or dropped (made for kids, comments disabled) in a run mixed with charts, so this is
  inconclusive, not a no.
* Not tried: `videoDuration`/`videoDefinition` filters, other `regionCode` values, other query words, `search.list
  type=channel`, a `1mo-6mo` window of 24 hours and a `1y-3y` window of 72 hours (set from their neighbours, not measured).

## You should be able to explain

1. Why a corpus from the first search results would fail on small channels, and how the strata prevent that.
2. Why a date-ordered search with no `q` returned almost only well-viewed videos, what a common word changed, and why the
   window has to widen with the age band.
3. Why `view_band` and `subscriber_band` cannot be requested from the API, and how the crawler still steers them (the
   quota after enrichment, the view band that picks the kind of search).
4. Why cleaning must be one shared function, and what goes wrong if training and serving clean differently.
5. Why the language check runs on text without mentions and URLs, and why 0.8.
6. Why duplicates are removed across the whole corpus and not per video. What would the model learn from spam?
7. Why sample 25 of the filtered comments at random instead of taking the first 25.
8. What `search.list` costs now, what limits a crawl, and why the main meter does not move for searches.
9. Why the author is hashed with a salt, and why no salt means no identifier at all.
10. What the TTL index guarantees, and why labels cannot live only in this collection.
11. Why a category that rejects a filter is skipped and a quota error is not.
12. How `over_quota` decides, why the target is shared among the non-empty bands (and at least three), and what the
    25% slack and the 10-video floor are for. What would an exact 20% rule do?
13. Why the quota runs after enrichment and before the comment pages, and what it costs in search calls that give nothing.
14. Why a view band is given up after three fruitless rounds in a row but a pair after two in total, and what a run that
    ends as `no_new_videos` with many `over_quota_*` drops tells you.
15. Equal shares on four axes at once: why the supply of candidates, not the code, decides how many videos a search call
    yields, and which constant you would loosen first.
16. What an observation of a search index (one window per row, one day) can and cannot prove.
