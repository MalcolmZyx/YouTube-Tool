"""Public YouTube data maintenance. Run from apps/api:

    python -m youtube purge                 delete expired public data now (MongoDB also does it by itself)
    python -m youtube refresh <client_id>   fetch or renew public data for one client (needs YOUTUBE_API_KEY)
    python -m youtube crawl --videos N      build the comment corpus until N videos are kept (needs YOUTUBE_API_KEY)
    python -m youtube coverage              show how balanced the comment corpus is
"""
import argparse
import random
import uuid
from collections.abc import Sequence

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from config import get_api_key, settings
from db.session import get_engine
from youtube import comment_store, comments, crawler, quota, store, strata
from youtube.client import Api, YouTubeError
from youtube.enrich import MIN_COMMENTS


def _crawl(args, engine: Engine | None, get=None) -> int:
    key = get_api_key()
    if not key:
        print("YOUTUBE_API_KEY is not set.")
        return 1
    api = Api(key, get)
    try:
        with Session(engine or get_engine()) as session, session.begin():
            summary = crawler.crawl(
                api, args.videos, args.seed, max_pages=args.max_pages, per_video_cap=args.per_video_cap,
                min_comments=args.min_comments, salt=settings.comment_author_salt,
                unit_budget=quota.get_status(session).remaining)
            quota.record(session, api.main_units)
            if summary.stop_reason == "quota_exceeded":
                quota.mark_exhausted(session)
    except (YouTubeError, comment_store.StoreError) as exc:
        print(f"Stopped: {exc}")
        return 1
    print(f"Stopped: {summary.stop_reason.replace('_', ' ')} after {summary.rounds} rounds.")
    print(f"Kept {summary.videos_kept} videos and {summary.comments_kept} comments.")
    if summary.dropped:
        print("Dropped: " + ", ".join(f"{reason} {n}" for reason, n in sorted(summary.dropped.items())))
    spent = ", ".join(f"{method} {n}" for method, n in sorted(summary.units.items())) or "none"
    print(f"Units spent: {spent} (search calls are in their own daily bucket of 100).")
    return 0


def _coverage() -> int:
    try:
        cov = strata.coverage(comment_store.coverage_rows())
    except comment_store.StoreError as exc:
        print(f"Stopped: {exc}")
        return 1
    orders = {
        "category_id": list(strata.CATEGORIES), "view_band": strata.VIEW_BANDS,
        "subscriber_band": strata.SUBSCRIBER_BANDS, "age_band": strata.AGE_BANDS,
    }
    total = sum(count.comments for count in cov.axes["age_band"].values())
    for axis, values in orders.items():
        print(f"\n{axis:<16}{'videos':>8}{'comments':>10}{'share':>8}")
        for value in values:
            count = cov.axes[axis].get(value)
            videos, kept = (count.videos, count.comments) if count else (0, 0)
            label = f"{value} {strata.CATEGORIES[value]}" if axis == "category_id" else value
            print(f"  {label:<30}{videos:>8}{kept:>10}{kept / total if total else 0:>8.0%}")
    possible = len(strata.CATEGORIES) * len(strata.VIEW_BANDS) * len(strata.SUBSCRIBER_BANDS) * len(strata.AGE_BANDS)
    print(f"\nCells with data: {len(cov.cells)} of {possible}.")
    print("Emptiest category x age band, searched next:")
    for category, band in strata.next_targets(cov, random.Random(0), 10):
        print(f"  {strata.CATEGORIES[category]:<24}{band:<10}{cov.pair(category, band).comments:>6} comments")
    return 0


def main(argv: Sequence[str] | None = None, engine: Engine | None = None, get=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m youtube", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("purge")
    refresh = sub.add_parser("refresh")
    refresh.add_argument("client_id", type=uuid.UUID)
    refresh.add_argument("--force", action="store_true", help="refetch even data that is still fresh")
    crawl = sub.add_parser("crawl")
    crawl.add_argument("--videos", type=int, required=True, help="stop after keeping this many videos")
    crawl.add_argument("--seed", type=int, default=0, help="makes the choices repeatable")
    crawl.add_argument("--max-pages", type=int, default=comments.MAX_PAGES, help="comment pages per video (100 each)")
    crawl.add_argument("--per-video-cap", type=int, default=comments.PER_VIDEO_CAP, help="comments kept per video")
    crawl.add_argument("--min-comments", type=int, default=MIN_COMMENTS, help="skip videos with fewer comments")
    sub.add_parser("coverage")
    args = parser.parse_args(argv)

    if args.command == "crawl":
        return _crawl(args, engine, get)
    if args.command == "coverage":
        return _coverage()
    if args.command == "purge":
        try:
            print(f"Purged {store.purge_expired() + comment_store.purge_expired()} expired documents.")
        except store.StoreError as exc:
            print(f"Stopped: {exc}")
            return 1
        return 0
    with Session(engine or get_engine()) as session, session.begin():
        key = get_api_key()
        if not key:
            print("YOUTUBE_API_KEY is not set.")
            return 1
        try:
            result = store.refresh_client(session, args.client_id, key, force=args.force)
        except (YouTubeError, store.StoreError) as exc:
            print(f"Stopped: {exc}")
            return 1
        print(f"{result.requested} needed data: {result.stored} stored, {result.unavailable} unavailable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
