"""The metric catalog: loading it from the seed files and resolving export column headers.

Seed files (db/seed/*.csv) are the reviewed source of truth, kept in git. `sync_metric_catalog`
copies them into the database and is safe to run repeatedly.

When "ratio" metrics are combined across videos, the value is numerator / denominator, multiplied
by 100 when the metric's unit is "percent". "weighted_avg" metrics are averaged using the weight
metric's values. "sum" metrics are added. "none" metrics cannot be combined.
"""
import csv
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from db.models import Metric, MetricAlias

SEED_DIR = Path(__file__).parent / "seed"

# Export columns that describe the video rather than measure it. They are not metrics.
ATTRIBUTE_HEADERS = frozenset({"content", "video title", "video publish time", "duration"})

_MAX_KEY_LENGTH = 60


def normalize_header(header: object) -> str:
    """Lower case with whitespace collapsed, so header spelling differences do not matter."""
    return " ".join(str(header).split()).lower()


def _read_csv(name: str) -> list[dict[str, str]]:
    with (SEED_DIR / name).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def sync_metric_catalog(session: Session) -> int:
    """Insert or update the seeded metrics and aliases. Returns the number of seeded metrics."""
    rows = _read_csv("metrics.csv")

    def values(row: dict[str, str]) -> dict[str, str | None]:
        return {
            "key": row["key"],
            "display_name": row["display_name"],
            "family": row["family"],
            "unit": row["unit"],
            "aggregation": row["aggregation"],
            "numerator_key": row["numerator_key"] or None,
            "denominator_key": row["denominator_key"] or None,
            "weight_key": row["weight_key"] or None,
            "description": row["description"] or None,
            "review_status": "reviewed",
        }

    # Ratio and weighted metrics point at other metrics, so those must exist first.
    ordered = [r for r in rows if r["aggregation"] not in ("ratio", "weighted_avg")] + [
        r for r in rows if r["aggregation"] in ("ratio", "weighted_avg")
    ]
    for row in ordered:
        statement = insert(Metric).values(values(row))
        updatable = {c: statement.excluded[c] for c in values(row) if c != "key"}
        session.execute(statement.on_conflict_do_update(index_elements=["key"], set_=updatable))

    aliases = {normalize_header(r["display_name"]): r["key"] for r in rows}
    aliases.update({normalize_header(r["alias"]): r["metric_key"] for r in _read_csv("metric_aliases.csv")})
    for alias, key in aliases.items():
        statement = insert(MetricAlias).values(alias=alias, metric_key=key)
        session.execute(statement.on_conflict_do_update(index_elements=["alias"], set_={"metric_key": key}))

    session.flush()
    return len(rows)


def find_metric_key(session: Session, header: object) -> str | None:
    """The catalog key for an export column header, or None if the header is unknown."""
    return session.scalar(select(MetricAlias.metric_key).where(MetricAlias.alias == normalize_header(header)))


def _slug(normalized_header: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", normalized_header).strip("_")[:_MAX_KEY_LENGTH].strip("_")
    if not slug or not slug[0].isalpha():
        slug = f"m_{slug}".strip("_")
    return slug


def get_or_register_metric(session: Session, header: object) -> str:
    """Resolve a header to a metric key, registering unknown headers instead of discarding them.

    A new header becomes an "unreviewed" metric (unit count, not combinable, family "unmapped") with
    an alias for the header, so its values are stored and it can be reviewed and classified later.
    """
    existing = find_metric_key(session, header)
    if existing:
        return existing

    alias = normalize_header(header)
    base = _slug(alias)
    key, suffix = base, 1
    while session.get(Metric, key) is not None:
        suffix += 1
        key = f"{base}_{suffix}"

    session.add(
        Metric(
            key=key,
            display_name=str(header).strip(),
            family="unmapped",
            unit="count",
            aggregation="none",
            review_status="unreviewed",
        )
    )
    session.flush()  # the alias references the metric row
    session.add(MetricAlias(alias=alias, metric_key=key))
    session.flush()
    return key
