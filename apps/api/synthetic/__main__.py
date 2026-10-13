"""Fake channels for demos and tests. Run from apps/api:

    python -m synthetic files <folder>    write one Studio-style export per fake channel
    python -m synthetic seed              create the fake clients in the database and import their exports
"""
import argparse
import hashlib
import tempfile
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from db.catalog import sync_metric_catalog
from db.models import Client, Upload
from db.session import get_engine
from ingest.importer import import_export
from synthetic.generator import PROFILES, write_export

MARKER = "[synthetic]"  # in the notes of every fake client, so they are easy to tell from real ones


def seed(session: Session) -> list[tuple[str, int, bool]]:
    """Create the fake clients (once) and import their exports. Returns (name, videos, newly imported)."""
    sync_metric_catalog(session)
    results = []
    with tempfile.TemporaryDirectory() as folder:
        for profile in PROFILES:
            client = session.scalar(select(Client).where(Client.name == profile.name, Client.notes == MARKER))
            if client is None:
                client = Client(name=profile.name, notes=MARKER)
                session.add(client)
                session.flush()
            # Not left to the file hash: an .xlsx embeds its creation time, so the same data hashes differently.
            if session.scalar(select(Upload.id).where(Upload.client_id == client.id).limit(1)) is not None:
                results.append((profile.name, profile.videos, False))
                continue
            path = write_export(profile, Path(folder))
            result = import_export(
                session, client_id=client.id, path=path, filename=path.name,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            results.append((profile.name, result.videos, not result.duplicate))
    return results


def main(argv: Sequence[str] | None = None, engine: Engine | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m synthetic", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    files = sub.add_parser("files")
    files.add_argument("folder", type=Path)
    sub.add_parser("seed")
    args = parser.parse_args(argv)

    if args.command == "files":
        args.folder.mkdir(parents=True, exist_ok=True)
        for profile in PROFILES:
            print(write_export(profile, args.folder))
        return 0

    with Session(engine or get_engine()) as session, session.begin():
        for name, videos, new in seed(session):
            print(f"{name}: {videos} videos, {'imported' if new else 'already imported'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
