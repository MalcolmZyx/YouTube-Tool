"""Database maintenance commands. Run from apps/api:

    python -m db sync-catalog      load the metric catalog (db/seed/*.csv) into the database

Schema changes are not here: they are applied with `alembic upgrade head`.
"""
import argparse
from collections.abc import Sequence

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from db.catalog import sync_metric_catalog
from db.session import get_engine


def main(argv: Sequence[str] | None = None, engine: Engine | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m db", description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["sync-catalog"])
    parser.parse_args(argv)

    with Session(engine or get_engine()) as session, session.begin():
        count = sync_metric_catalog(session)
    print(f"Metric catalog synced: {count} metrics.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
