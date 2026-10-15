"""Public YouTube data maintenance. Run from apps/api:

    python -m youtube purge                 delete expired public data now (MongoDB also does it by itself)
    python -m youtube refresh <client_id>   fetch or renew public data for one client (needs YOUTUBE_API_KEY)
"""
import argparse
import uuid
from collections.abc import Sequence

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from config import get_api_key
from db.session import get_engine
from youtube import store
from youtube.client import YouTubeError


def main(argv: Sequence[str] | None = None, engine: Engine | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m youtube", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("purge")
    refresh = sub.add_parser("refresh")
    refresh.add_argument("client_id", type=uuid.UUID)
    refresh.add_argument("--force", action="store_true", help="refetch even data that is still fresh")
    args = parser.parse_args(argv)

    if args.command == "purge":
        try:
            print(f"Purged {store.purge_expired()} expired documents.")
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
