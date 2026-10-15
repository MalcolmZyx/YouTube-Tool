# The analytics layer (dbt)

Code: [`pipeline/dbt/`](../../pipeline/dbt/). Cross-check: [`pipeline/check_marts_match_audit.py`](../../pipeline/check_marts_match_audit.py).

## What dbt is, in one paragraph

dbt turns a folder of `SELECT` statements into tables, in the right order, with tests and documentation. You write each
model as plain SQL; `{{ ref('other_model') }}` tells dbt what it depends on, so it builds a dependency graph, runs
models in order, runs the tests you declared, and generates a documentation site with a lineage graph. It does not move
data: the data is already in Postgres. It only transforms it, which is why it is called the "T" of ELT.

## Layers

```
 app tables (public)        staging (views)               marts (tables)                     read by
 client, upload, video  ──►  stg_client, stg_upload,  ──►  mart_video_performance           BI tools later
 video_metric, upload_       stg_video, stg_video_         mart_channel_cadence             (Metabase, Power BI,
 total, metric               metric, stg_upload_total      mart_format_summary               Tableau)
                                                           mart_client_overview
```

* **Sources** are the application's own tables, written only by the importer. dbt never writes to them.
* **Staging** (views) renames and lightly cleans, one model per source table, with no business logic except two
  definitions that must live in exactly one place: each upload's `as_of_date` and each client's `is_latest_upload`.
* **Marts** (tables) are what people and BI tools read. Each one states its **grain** (what one row is), because a
  mart whose grain is unclear gets double counted. Marts are tables, computed once per build, so a dashboard is a plain
  fast `SELECT`.

## The marts

| Mart | Grain (one row is...) | Use |
|---|---|---|
| `mart_video_performance` | a video in one upload | the wide per-video table; a column per headline metric, built by pivoting the long `video_metric` rows |
| `mart_channel_cadence` | a client in one month | uploads, Shorts and long-form per month |
| `mart_format_summary` | an upload and a format (Short or long-form) | counts, totals, medians and an impressions-weighted click rate |
| `mart_client_overview` | a client | headline numbers plus two cross-checks: the gap between the export's Total and the listed videos, and how concentrated views are in the top 10% |

A missing metric is `NULL`, never 0 (the same rule as the importer), and a click rate is **weighted by impressions**,
never averaged across videos.

## Why SQL for this, and Python for the audit

The audit does statistics (rank tests, bootstrap ranges, multiple-comparison correction): that belongs in Python. The
marts do **shaping that has one agreed definition**: join, pivot, group, median. That belongs in versioned, tested SQL
that a BI tool, an analyst or a notebook can all read and trust. Keeping the boundary clear avoids two places deciding
the same thing differently, which leads to the next point.

## Two implementations, checked against each other

The Python audit and the SQL marts both compute medians, the top-10% share and the weighted click rate, from the same
database, written independently. `check_marts_match_audit.py` compares them (14 numbers across 4 clients) and fails the
build on any disagreement. CI runs it after every `dbt build`. If one implementation had a bug, they would disagree.
(Aligning them found that "weighted" needed the same rule for rows with a missing click rate in both places.)

## Tests

40 tests: `unique`, `not_null`, `relationships` (a foreign key between models), `accepted_values`, two custom generic
tests (`unique_combination` for composite grains, `between_zero_and_one`), and singular tests written as SQL that
must return zero rows: counts are never negative, a click rate is between 0 and 100, each client has exactly one
latest upload, no video is younger than zero days.

**A real finding:** the first build failed `assert_counts_are_never_negative` on your real export, where one video has
**Dislikes = -1**. A period export reports changes, so a reaction count can go slightly negative when a reaction is
removed. The rule was too strong for reaction counts, so it was split: true counts (views, shares, ...) still fail the
build if negative, while likes and dislikes only **warn** (visible in the output, not blocking). The test was
changed because the data taught us the rule was wrong, not to make it pass.

## Running it

```bash
python -m venv .dbt-venv && .dbt-venv/Scripts/activate        # dbt has its own environment (see requirements-dbt.txt)
pip install -r pipeline/requirements-dbt.txt
cd pipeline/dbt
dbt build --profiles-dir .          # builds staging and marts, runs every test
dbt docs generate --profiles-dir . && dbt docs serve --profiles-dir .      # the documentation site and lineage graph
```

dbt connects with the same development defaults as `docker-compose.yml` (override with `DBT_HOST`, `DBT_PORT`, `DBT_USER`,
`DBT_PASSWORD`, `DBT_DBNAME`). It creates two schemas, `staging` and `marts`, and leaves the application tables alone.
dbt has its own virtual environment because it pins many of its own dependencies and the two sets would fight.

## What is not here yet

* **Incremental models and snapshots:** the data is tiny, so every build recomputes everything. Worth it at scale.
* **The raw landing zone (MongoDB)** that was planned alongside this: next.
* **Orchestration:** `make ingest` style one-command runs, and a schedule, are a deployment-phase job.
* **Column descriptions** are written for the important columns, not all of them.

## You should be able to explain

1. What dbt does and does not do. Why are staging models views and marts tables?
2. What is a model's grain, and what goes wrong when it is unclear?
3. How is the long `video_metric` table turned into a wide one, and why is a missing metric NULL and not 0?
4. Why is a click-through rate weighted by impressions, and what would a plain average do?
5. What does `relationships` test? What does a singular test look like?
6. Why does the build compare the SQL marts with the Python audit? What would a mismatch mean?
7. The first run failed on `Dislikes = -1`. What did we change, and why was changing the test the right call?
8. Why does dbt have its own virtual environment?
9. Where is the line between what dbt does and what the Python audit does?
