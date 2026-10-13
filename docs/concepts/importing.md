# Importing exports

How a Studio export becomes rows in the database, the rules it follows, and how to add a new kind of export.
Code: [`apps/api/ingest/`](../../apps/api/ingest/), [`apps/api/intake.py`](../../apps/api/intake.py),
[`apps/api/routers/clients.py`](../../apps/api/routers/clients.py). The tables are explained in
[data-model.md](data-model.md).

## The flow

```
upload (HTTP) ──► intake.spool_upload ──► ingest.import_export ──► tables
                  size cap, extension      already imported? ──yes──► return the existing upload (200)
                  SHA-256 while copying    read file ► detect report type ► importer ► one transaction
```

For a "Table data" export the importer:

1. separates the `Total` row from the videos (the Total is a summary, not a video);
2. skips rows whose video ID is not 11 URL-safe characters, and repeated IDs, each with a warning;
3. maps every other column to a catalog metric through its header (unknown headers are registered as `unreviewed`);
4. creates the `upload`, creates or refreshes the `video` rows, and bulk-inserts `video_metric` and `upload_total`;
5. compares the videos with the Total row for additive metrics and warns about clear gaps.

## Rules and why

**One transaction.** The whole import commits or none of it does. A rejected file leaves no half-imported upload.

**Idempotent by file hash.** The SHA-256 of the bytes identifies a file, computed while it is copied. The same file
for the same client is detected, answered with `200` and `duplicate: true`, and changes nothing. A different file
for the same period is a new upload, so history is kept.

**Blank is not zero.** A blank cell stores no row ("not reported"); a `0` stores a row with value 0. Excel cells keep
their types and CSV cells are text, so the parsers accept both (`"1,234"`, `"4.75%"`, `00:00:56`, an Excel time).
Times become seconds. Markers pandas reads as missing (`n/a`, `NA`) are treated as blank.

**A blank never erases knowledge.** Re-importing refreshes a video's title, publish date and duration, but a blank in
the new file keeps the value an earlier file gave (`COALESCE`).

**Unknown columns are kept.** A header the catalog has never seen becomes an `unreviewed` metric with its values
stored, and the import response lists it so it can be reviewed. Nothing is dropped and nothing blocks the import.

**The date range is not guessed.** A Studio export does not state its range. It is taken from the request if the
operator gives one (`user`), otherwise from a `YYYY-MM-DD_YYYY-MM-DD` pattern in the file name (`filename`), otherwise
it stays `unknown`, and `PUT .../period` confirms it later. The file-name pattern is an assumption about Studio's
naming and is recorded as such.

**Limits.** File size and number of videos are capped (`MAX_UPLOAD_MB`, `MAX_ROWS`) because each video can cost a
YouTube API call and a huge file ties up a worker.

## What real data taught

* On the sample export the Total row's **subscriber** figures are far larger than the sum over videos (net 303 vs 162,
  gained 456 vs 167). Subscribers are partly credited to the channel, not to a video, so "the videos add up to the
  total" is not true for every metric. The reconciliation message says so instead of blaming deleted videos.
* **A route that commits after the response is a bug.** The first version of the session dependency committed *after*
  the response was sent (FastAPI's default dependency scope), so a client could delete a record, be told `200`, and
  read it straight back. Driving the real server found it; `Depends(get_session, scope="function")` fixes it and a test
  guards every route. In-process tests could not have caught it.

## Adding a new kind of export (for example traffic source)

1. Look at a real sample and decide its **grain** (one row per traffic source per upload) and what it measures.
2. Add a table for it (for example `breakdown_metric`) with composite foreign keys that carry `client_id`, and an
   Alembic migration.
3. Write a detector (`_looks_like_traffic_source(df)`) and an importer function modelled on `_import_table_data`.
4. Register both in `REPORT_TYPES` in `ingest/importer.py`, and allow the new `report_type` in the `upload` CHECK.
5. Add tests like the ones in `tests/test_importer.py`. The route, hashing, idempotency, period and rejection handling
   are shared and need no changes.

## You should be able to explain

1. Why is the import one transaction, and what does the caller see if it fails halfway?
2. How is "the same file" decided, and why a hash and not the file name?
3. What is stored for a blank cell, for a `0`, and for text like `abc`? Why?
4. Why does the Total row not become a video, and why can it disagree with the sum of the videos?
5. What happens to a column the catalog has never seen?
6. Why is the period `unknown` by default, and how does it get set?
7. What bug did driving the real server reveal, and why could the unit tests not see it?
8. Which steps add a new report type, and which parts need no change?
