"""Recording a decision about a comment, and taking it back."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import CommentLabel
from labeling import comments
from youtube.store import utcnow

STATUS = {
    "constructive": "constructive", "not_constructive": "not_constructive", "discard": "discarded", "skip": "skipped",
}
KEPT = ("constructive", "not_constructive")  # these keep the comment text; the other two keep only the id

_SNAPSHOT = ("text", "video_id", "video_title", "stratum", "like_count", "published_at")
_STATE = ("status", "depth", "aspects", "queue_mode", "labeled_at", "updated_at") + _SNAPSHOT
_TIMES = ("published_at", "labeled_at", "updated_at")


class CommentGone(Exception):
    """The comment expired from MongoDB and there is no stored copy of it to label."""


def _state(row: CommentLabel) -> dict:
    """The row's fields as JSON, kept in `previous` so the next change can be undone."""
    state = {name: getattr(row, name) for name in _STATE}
    return {k: v.isoformat() if k in _TIMES and v else v for k, v in state.items()}


def _restore(row: CommentLabel, state: dict) -> None:
    for name, value in state.items():
        setattr(row, name, datetime.fromisoformat(value) if name in _TIMES and value else value)
    row.previous = None


def _from_row(row: CommentLabel) -> dict:
    return {
        "comment_id": row.comment_id, "text": row.text, "video_id": row.video_id, "video_title": row.video_title,
        "like_count": row.like_count or 0, "published_at": row.published_at, "stratum": row.stratum or {},
    }


def record(
    session: Session, comment_id: str, decision: str, depth: str | None, aspects: list[str], queue_mode: str
) -> None:
    """Save the decision, replacing an earlier one for the same comment. Repeating a decision changes nothing.

    A kept label copies the text out of MongoDB so it outlives the 30-day expiry. If the comment has expired since it
    was shown, a stored copy is used when there is one; otherwise `CommentGone` is raised and nothing is written.
    """
    status = STATUS[decision]
    row = session.get(CommentLabel, comment_id, with_for_update=True)
    unchanged = row and (row.status, row.depth, list(row.aspects)) == (status, depth, aspects)
    if unchanged and (row.text or status not in KEPT):
        return

    live = comments.find(comment_id)
    if live is None and (row is None or (status in KEPT and row.text is None)):
        raise CommentGone
    source = live or (_from_row(row) if row else {})

    previous = _state(row) if row else None
    if row is None:
        row = CommentLabel(comment_id=comment_id)
        session.add(row)
    now = utcnow()
    row.status, row.depth, row.aspects, row.queue_mode = status, depth, aspects, queue_mode
    row.labeled_at = row.updated_at = now
    for name in _SNAPSHOT:
        setattr(row, name, source.get(name) if status in KEPT else None)
    row.previous = previous
    session.flush()


def undo(session: Session) -> tuple[bool, dict | None]:
    """Revert the most recent change: delete the row if the comment was unlabeled before, else restore its old state.

    Returns whether anything was undone and the comment to show again (None if it has expired and was never kept).
    """
    latest = select(CommentLabel).order_by(CommentLabel.updated_at.desc(), CommentLabel.comment_id)
    row = session.scalars(latest.limit(1).with_for_update()).first()
    if row is None:
        return False, None
    shown = _from_row(row) if row.text else comments.find(row.comment_id)
    if row.previous is None:
        session.delete(row)
    else:
        _restore(row, row.previous)
    session.flush()
    return True, shown
