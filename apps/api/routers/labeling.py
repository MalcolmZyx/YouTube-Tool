"""Labeling comments for the constructive-criticism classifier: the queue, the decisions and the progress figures."""
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

import deps
from db.models import CommentLabel
from labeling import comments, labels, stats
from schemas import CommentOut, LabelIn, LabelResultOut, LabelStatsOut, QueueMode, QueueOut, UndoOut
from youtube import store

router = APIRouter(prefix="/labeling", tags=["labeling"])


def _store_errors(exc: store.StoreError) -> HTTPException:
    return HTTPException(status_code=503 if isinstance(exc, store.StoreNotConfigured) else 502, detail=str(exc))


def _queue(session: Session, count: int, avoid: str | None = None) -> list[CommentOut]:
    rows = session.execute(select(CommentLabel.comment_id, CommentLabel.status)).all()
    skipped = [r.comment_id for r in rows if r.status == "skipped"]
    found = comments.next_comments([r.comment_id for r in rows], skipped, count, avoid)
    return [CommentOut(**c) for c in found]


@router.get("/queue", response_model=QueueOut)
def get_queue(
    session: deps.SessionDep,
    mode: QueueMode = "random",
    count: Annotated[int, Query(ge=1, le=50)] = 8,
) -> QueueOut:
    """The comment to label now and a preview of the ones after it.

    Never-seen comments come first in random order across the whole pool, with neighbours from different videos where
    possible; skipped comments are only offered once the never-seen ones run out. Replies and expired comments are
    left out.
    """
    try:
        return QueueOut(mode=mode, items=_queue(session, count))
    except store.StoreError as exc:
        raise _store_errors(exc) from None


@router.post("/labels", response_model=LabelResultOut)
def save_label(body: LabelIn, session: deps.SessionDep) -> LabelResultOut:
    """Record a decision (replacing an earlier one for the comment) and return the new figures and the next comment."""
    try:
        labels.record(session, body.comment_id, body.decision, body.depth, body.aspects, body.queue_mode)
        following = _queue(session, 1, avoid=body.comment_id)
        return LabelResultOut(stats=stats.collect(session), next=following[0] if following else None)
    except labels.CommentGone:
        raise HTTPException(status_code=404, detail="This comment has expired and can no longer be labeled.") from None
    except store.StoreError as exc:
        raise _store_errors(exc) from None


@router.post("/labels/undo", response_model=UndoOut)
def undo_label(session: deps.SessionDep) -> UndoOut:
    """Revert the most recent decision, and return the comment so it can be decided again."""
    try:
        done, shown = labels.undo(session)
        if not done:
            raise HTTPException(status_code=404, detail="Nothing to undo.")
        return UndoOut(stats=stats.collect(session), undone=CommentOut(**shown) if shown else None)
    except store.StoreError as exc:
        raise _store_errors(exc) from None


@router.get("/stats", response_model=LabelStatsOut)
def get_stats(session: deps.SessionDep, mode: QueueMode = "random") -> LabelStatsOut:
    """Counts per decision, the share of constructive comments with its 95% interval, and breakdowns of the tags.

    The share is only meaningful for queue mode 'random'; it is computed from the labels that mode served.
    """
    try:
        return LabelStatsOut(**stats.collect(session, mode))
    except store.StoreError as exc:
        raise _store_errors(exc) from None
