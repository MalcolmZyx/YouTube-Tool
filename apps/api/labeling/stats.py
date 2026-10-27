"""Progress figures for the labeling page."""
from datetime import datetime
from math import sqrt

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from db.models import LABEL_ASPECTS, LABEL_DEPTHS, LABEL_STATUSES, CommentLabel
from labeling import comments

Z_95 = 1.96  # the normal quantile that leaves 2.5% in each tail

PREVALENCE_NOTE = (
    "The share of constructive comments is only an estimate of how common they are when every label came from the "
    "random queue. Labels from any other queue mode are left out of it, because those queues choose comments on "
    "purpose."
)


def wilson_interval(successes: int, n: int, z: float = Z_95) -> tuple[float, float] | None:
    """The Wilson score interval for a proportion: where the true share plausibly lies given `n` labels.

    Unlike the textbook p +/- z*sqrt(p(1-p)/n), it stays inside 0..1 and is sensible with few labels or a rare class.
    """
    if n == 0:
        return None
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def _start_of_today() -> datetime:
    return datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)


def collect(session: Session, mode: str = "random") -> dict:
    counts = dict.fromkeys(LABEL_STATUSES, 0)
    counts.update(session.execute(select(CommentLabel.status, func.count()).group_by(CommentLabel.status)).all())
    constructive, not_constructive = counts["constructive"], counts["not_constructive"]

    in_mode = {s: session.scalar(select(func.count()).where(CommentLabel.status == s, CommentLabel.queue_mode == mode))
               for s in ("constructive", "not_constructive")}
    n = in_mode["constructive"] + in_mode["not_constructive"]
    interval = wilson_interval(in_mode["constructive"], n)

    kept = CommentLabel.status.in_(("constructive", "not_constructive"))
    today = session.scalar(select(func.count()).where(kept, CommentLabel.labeled_at >= _start_of_today()))

    by_depth = dict.fromkeys((*LABEL_DEPTHS, "untagged"), 0)
    tagged = select(CommentLabel.depth, func.count()).where(CommentLabel.status == "constructive")
    for depth, number in session.execute(tagged.group_by(CommentLabel.depth)):
        by_depth[depth or "untagged"] = number

    by_aspect = dict.fromkeys(LABEL_ASPECTS, 0)
    for name, number in session.execute(
        text("SELECT aspect, count(*) FROM comment_label, unnest(aspects) AS aspect GROUP BY aspect")
    ):
        by_aspect[name] = number

    category = CommentLabel.stratum["category_id"].astext
    by_category = [
        {"category_id": cat, "constructive": c, "not_constructive": nc}
        for cat, c, nc in session.execute(
            select(
                category,
                func.count().filter(CommentLabel.status == "constructive"),
                func.count().filter(CommentLabel.status == "not_constructive"),
            ).where(kept).group_by(category).order_by(func.count().desc(), category)
        )
    ]

    decided = session.scalars(select(CommentLabel.comment_id).where(CommentLabel.status != "skipped")).all()
    return {
        "counts": counts,
        "labeled_total": constructive + not_constructive,
        "labeled_today": today,
        "remaining": comments.remaining(decided),
        "prevalence": {
            "queue_mode": mode, "n": n, "constructive": in_mode["constructive"],
            "share": in_mode["constructive"] / n if n else None,
            "low": interval[0] if interval else None, "high": interval[1] if interval else None,
            "note": PREVALENCE_NOTE,
        },
        "by_depth": by_depth, "by_aspect": by_aspect, "by_category": by_category,
    }
