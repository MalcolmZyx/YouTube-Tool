"""Cross-check: the dbt marts (SQL) must agree with the Python audit on every number they both compute.

Two independent implementations of the same definitions (medians, the top-10% share, the impressions-weighted click
rate) are the best test of both. Run after `dbt build`, from the repository root, with the API's dependencies installed:

    python pipeline/check_marts_match_audit.py

Exits 1 and prints every disagreement if any number differs by more than a rounding error.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from audit.service import build_audit  # noqa: E402
from db.session import get_engine  # noqa: E402

TOLERANCE = 1e-6


def close(a, b) -> bool:
    return a is None and b is None or (a is not None and b is not None and math.isclose(a, b, rel_tol=TOLERANCE))


def main() -> int:
    problems, checked = [], 0
    with Session(get_engine()) as session:
        clients = session.execute(text(
            "select client_id, client_name from marts.mart_client_overview where latest_upload_id is not null")).all()
        for client_id, name in clients:
            audit = build_audit(session, client_id)
            findings = {f["key"]: f["details"] for f in audit["findings"]}

            overview = session.execute(text(
                "select top_decile_share, listed_views from marts.mart_client_overview where client_id = :c"),
                {"c": client_id}).one()
            expected = [("top 10% share", findings["overview"].get("top_decile_share"), overview.top_decile_share)]

            formats = {r.is_short: r for r in session.execute(text(
                "select f.is_short, f.median_views, f.weighted_ctr_pct from marts.mart_format_summary f "
                "join staging.stg_upload u using (upload_id) where u.is_latest_upload and f.client_id = :c"),
                {"c": client_id})}
            if findings["formats"].get("strength") != "not_enough_data" and findings["formats"].get("n_a") is not None:
                expected += [
                    ("Shorts median views", findings["formats"]["median_a"], formats[True].median_views),
                    ("long-form median views", findings["formats"]["median_b"], formats[False].median_views),
                ]
            if "channel_ctr" in findings["click_through"]:
                expected.append(("channel click rate", findings["click_through"]["channel_ctr"],
                                 _weighted_ctr(session, client_id)))

            for label, python_value, sql_value in expected:
                checked += 1
                sql_value = None if sql_value is None else float(sql_value)
                if not close(python_value, sql_value):
                    problems.append(f"{name}: {label}: audit says {python_value}, marts say {sql_value}")

    for line in problems:
        print("MISMATCH", line)
    print(f"{checked} numbers compared across {len(clients)} clients: {'all agree' if not problems else 'DISAGREE'}")
    return 1 if problems else 0


def _weighted_ctr(session, client_id):
    """The click rate over the whole latest upload, from the mart (both formats together)."""
    return session.execute(text(
        "select sum(impressions_ctr_pct * impressions) filter (where impressions > 0)"
        " / nullif(sum(impressions) filter (where impressions > 0 and impressions_ctr_pct is not null), 0) "
        "from marts.mart_video_performance where client_id = :c and is_latest_upload"), {"c": client_id}).scalar()


if __name__ == "__main__":
    raise SystemExit(main())
