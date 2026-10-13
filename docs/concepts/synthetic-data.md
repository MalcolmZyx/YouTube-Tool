# Synthetic data

Fake channels that look like real Studio exports. Code: [`apps/api/synthetic/`](../../apps/api/synthetic/).

## Why

* **Demos and screenshots** need data, and real client data must never be public.
* **Tests and UI work** need realistic volume (30 to 110 videos, a Total row, Shorts) without a creator's file.
* **Safety:** nothing here describes a real channel. Video IDs are random, titles come from a small template list.

## Commands (from `apps/api`)

```bash
python -m synthetic files ./out    # write one .xlsx per fake channel (to try the upload route by hand)
python -m synthetic seed           # create the three fake clients and import them; safe to run again
```

Fake clients carry the note `[synthetic]`, so they are easy to tell from real ones and to delete.

## How it is made

* **Seeded.** `numpy.random.default_rng(seed)` gives the same rows every run, so tests can assert on them.
* **Shaped like the real export.** Heavy-tailed views (log-normal), young videos not yet matured, Shorts without
  impressions or CTR, unused feature columns at 0, the Total row first, and subscribers on the Total larger than the
  sum over videos (credited to the channel).
* **Goes through the real importer.** The generator writes an .xlsx, and `seed` imports it with `import_export`, so the
  demo path exercises the same code as a real upload. It is not a database shortcut.
* **Fixed export date** (2026-10-01), so output never depends on today's date.

## A bug the first test run found

Seeding twice imported the data twice. The importer detects a repeated file by its SHA-256, but an `.xlsx` embeds its
creation time, so identical data produced a different hash each run. `seed` therefore checks whether the client already
has an upload instead of relying on the hash. Lesson: a content hash identifies *bytes*, not *meaning*.

## You should be able to explain

1. Why generate files and import them instead of inserting rows directly?
2. What does "seeded" buy you, and what would break without it?
3. Which real-data quirks did the generator copy, and why do they matter to the importer and later analysis?
4. Why did importing the same fake data twice not count as a duplicate, and how was it fixed?
