"""The audit engine: known answers on hand-built data, honest handling of thin data, and the route."""
import uuid
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import app
from audit.engine import (
    CTR,
    DURATION,
    ID,
    IMPRESSIONS,
    PUBLISHED,
    RETENTION,
    TITLE,
    VIEWS,
    Context,
    cadence,
    click_through,
    duration_effect,
    formats,
    overview,
    performance,
    retention,
    run_audit,
    title_features,
)
from audit.report import render_html
from audit.stats import compare, holm_adjust, log_linear_fit, spearman
from db.session import get_session
from synthetic.generator import PROFILES, write_export

AS_OF = date(2026, 10, 1)


def make_frame(rows):
    """rows: dicts with any of views, duration, age (days old), impressions, ctr."""
    return pd.DataFrame([
        {
            ID: f"{i:011d}", TITLE: f"Video {i}",
            PUBLISHED: pd.Timestamp(AS_OF - timedelta(days=r.get("age", 100))),
            DURATION: r.get("duration", 600), VIEWS: r.get("views", np.nan),
            IMPRESSIONS: r.get("impressions", np.nan), CTR: r.get("ctr", np.nan),
        }
        for i, r in enumerate(rows)
    ])


def ctx(rows, totals=None, period_kind="lifetime"):
    return Context(make_frame(rows), totals or {}, AS_OF, period_kind)


# ── statistics ──────────────────────────────────────────────────────────────


def test_a_clear_difference_is_solid_and_the_interval_excludes_one():
    c = compare(np.arange(100, 130), np.arange(10, 40))

    assert (c.n_a, c.n_b, c.strength) == (30, 30, "solid")
    assert c.ratio > 3 and c.ratio_low > 1 and c.effect > 0.9 and c.p_value < 0.001


def test_identical_groups_are_not_a_finding():
    values = np.arange(1, 31)

    c = compare(values, values)

    assert c.strength == "weak" and c.p_value > 0.9 and abs(c.effect) < 0.1 and c.ratio == 1


def test_tiny_groups_report_no_number():
    c = compare([1, 2, 3], [10, 20, 30, 40, 50, 60])

    assert (c.strength, c.p_value, c.ratio) == ("not_enough_data", None, None)


def test_groups_under_ten_are_weak_whatever_the_p_value():
    assert compare(np.arange(100, 108), np.arange(1, 9)).strength == "weak"


def test_results_are_reproducible():
    a, b = np.random.default_rng(1).lognormal(5, 1, 40), np.random.default_rng(2).lognormal(4.5, 1, 40)

    assert compare(a, b) == compare(a, b)


def test_log_linear_fit_recovers_a_power_law():
    age = np.arange(10, 400, 10)

    slope, _, r2 = log_linear_fit(age, 50 * age ** 0.5)

    assert slope == pytest.approx(0.5, abs=0.03) and r2 > 0.99


# ── findings ────────────────────────────────────────────────────────────────


def test_overview_measures_concentration_and_flags_a_total_that_exceeds_the_videos():
    rows = [{"views": 1000}] + [{"views": 10}] * 9

    f = overview(ctx(rows, totals={VIEWS: 5000}))

    assert f.details["top_decile_videos"] == 1 and f.details["top_decile_share"] == pytest.approx(1000 / 1090)
    assert f.details["total_views"] == 5000 and any("Total" in c for c in f.caveats)


def test_overview_without_views_says_so():
    assert overview(ctx([{}, {}])).strength == "not_enough_data"


def test_performance_ranks_a_video_that_beats_its_age_and_does_not_reward_age_alone():
    rows = [{"age": a, "views": 100 * (a ** 0.5)} for a in range(30, 330, 15)]
    rows.append({"age": 60, "views": 100 * 60 ** 0.5 * 8})  # a young hit
    rows.append({"age": 300, "views": 100 * 300 ** 0.5 * 0.1})  # an old flop

    f = performance(ctx(rows))

    best, worst = f.details["best"][0], f.details["worst"][0]
    assert best["age_days"] == 60 and best["index"] > 3
    assert worst["age_days"] == 300 and worst["index"] < 0.5
    assert f.details["best"][0]["index"] > f.details["best"][1]["index"]


def test_performance_ignores_videos_too_new_to_judge_and_needs_enough_videos():
    assert performance(ctx([{"age": 100, "views": 5}] * 4)).strength == "not_enough_data"
    new_only = [{"age": 3, "views": v} for v in range(1, 12)]
    assert performance(ctx(new_only)).strength == "not_enough_data"


def test_performance_warns_when_the_period_is_not_lifetime():
    rows = [{"age": a, "views": 50 + a} for a in range(30, 330, 20)]

    assert any("not confirmed as lifetime" in c for c in performance(ctx(rows, period_kind="unknown")).caveats)
    assert not any("not confirmed" in c for c in performance(ctx(rows, period_kind="lifetime")).caveats)


def test_cadence_counts_uploads_gaps_and_the_recent_trend():
    ages = [5, 20, 35, 50, 70, 200, 220, 240, 260, 400, 420]  # busy lately, a long gap, then older uploads

    f = cadence(ctx([{"age": a, "views": 1} for a in ages]))

    assert (f.details["last_90_days"], f.details["previous_90_days"]) == (5, 0)
    assert f.details["longest_gap_days"] == 140  # between the uploads 400 and 260 days ago
    assert f.details["longest_gap_ended"] == (AS_OF - timedelta(days=260)).isoformat()
    assert sum(f.details["by_weekday"].values()) == len(ages)
    assert "faster" in f.headline


def test_formats_find_a_real_difference_between_shorts_and_long_form():
    rng = np.random.default_rng(3)
    shorts = [{"duration": 30, "views": float(v)} for v in rng.lognormal(8, 0.4, 25)]
    long = [{"duration": 600, "views": float(v)} for v in rng.lognormal(6, 0.4, 25)]

    f = formats(ctx(shorts + long))

    assert f.strength == "solid" and f.details["ratio"] > 3 and f.details["ratio_low"] > 1
    assert "Shorts get more views" in f.headline


def test_formats_say_no_clear_difference_when_there_is_none():
    rng = np.random.default_rng(4)
    shorts = [{"duration": 30, "views": float(v)} for v in rng.lognormal(7, 0.5, 25)]
    long = [{"duration": 600, "views": float(v)} for v in rng.lognormal(7, 0.5, 25)]

    f = formats(ctx(shorts + long))

    assert f.headline.startswith("No clear difference")


def test_formats_with_too_few_of_one_kind_do_not_compare():
    f = formats(ctx([{"duration": 30, "views": 5}] * 2 + [{"duration": 600, "views": 7}] * 20))

    assert f.strength == "not_enough_data" and "too few" in f.headline


def test_click_through_flags_widely_shown_videos_with_low_clicks_and_ignores_blank_impressions():
    rows = [{"impressions": 10_000, "ctr": 6.0, "views": 600}] * 10
    rows += [{"impressions": 50_000, "ctr": 1.5, "views": 750}]  # shown to many, clicked rarely
    rows += [{"impressions": 100, "ctr": 0.5, "views": 1}] * 2  # tiny reach: not worth flagging
    rows += [{"views": 9_999}] * 5  # Shorts: no impressions at all

    f = click_through(ctx(rows))

    assert f.details["videos_with_impressions"] == 13  # the five blank ones are not zeros
    assert f.details["candidates"][0]["impressions"] == 50_000
    assert f.details["channel_ctr"] > 4  # weighted by impressions


def test_click_through_with_no_impressions_is_not_enough_data():
    assert click_through(ctx([{"views": 10}] * 20)).strength == "not_enough_data"


def test_the_whole_audit_runs_on_an_empty_channel_without_crashing():
    findings = run_audit(Context(make_frame([{}]), {}, AS_OF, "unknown"))

    assert [f.key for f in findings] == [
        "overview", "performance", "cadence", "formats", "duration", "title_features", "retention", "click_through"]
    assert {f.strength for f in findings} <= {"info", "not_enough_data"}


# ── the route, on the fake channels ─────────────────────────────────────────


@pytest.fixture
def api(catalog_session):
    app.dependency_overrides[get_session] = lambda: catalog_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def upload_channel(api, tmp_path, profile):
    client = api.post("/api/clients", json={"name": profile.name}).json()
    path = write_export(profile, tmp_path)
    with open(path, "rb") as fh:
        api.post(f"/api/clients/{client['id']}/uploads", files={"file": (path.name, fh.read())})
    return client["id"]


def test_audit_route_on_a_fake_channel_finds_the_planted_shorts_effect(api, tmp_path):
    client_id = upload_channel(api, tmp_path, PROFILES[0])  # the generator gives Shorts 1.6x the views

    body = api.get(f"/api/clients/{client_id}/audit").json()

    assert body["videos"] == PROFILES[0].videos and body["period_kind"] == "range"
    assert body["as_of"] == "2026-10-01" and "date range" in body["as_of_source"]
    findings = {f["key"]: f for f in body["findings"]}
    assert set(findings) == {"overview", "performance", "cadence", "formats", "duration", "title_features",
                             "retention", "click_through"}
    assert findings["formats"]["details"]["ratio"] > 1  # Shorts did better, as planted
    assert findings["click_through"]["details"]["videos_with_impressions"] > 0
    assert all(f["headline"] for f in body["findings"])


def test_audit_is_identical_on_every_run(api, tmp_path):
    client_id = upload_channel(api, tmp_path, PROFILES[1])

    assert api.get(f"/api/clients/{client_id}/audit").json() == api.get(f"/api/clients/{client_id}/audit").json()


def test_audit_of_a_small_channel_admits_what_it_cannot_say(api, tmp_path):
    client_id = upload_channel(api, tmp_path, PROFILES[1])  # 30 videos, only about 10% Shorts

    findings = {f["key"]: f for f in api.get(f"/api/clients/{client_id}/audit").json()["findings"]}

    assert findings["formats"]["strength"] in ("not_enough_data", "weak")


def test_audit_unknown_and_empty_clients_are_404(api):
    assert api.get(f"/api/clients/{uuid.uuid4()}/audit").status_code == 404
    empty = api.post("/api/clients", json={"name": "Empty"}).json()
    assert api.get(f"/api/clients/{empty['id']}/audit").status_code == 404


# ── title features, length, retention ───────────────────────────────────────


def test_holm_correction_raises_p_values_and_keeps_their_order():
    assert holm_adjust([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert holm_adjust([0.5]) == [0.5]
    assert all(a >= p for a, p in zip(holm_adjust([0.2, 0.001, 0.04]), [0.2, 0.001, 0.04], strict=True))


def test_spearman_finds_a_monotone_link_and_reports_nothing_for_tiny_samples():
    x = np.arange(40)
    clear = spearman(x, x ** 2)

    assert clear.rho == pytest.approx(1.0) and clear.low > 0.9 and clear.strength == "solid"
    assert spearman([1, 2, 3], [3, 2, 1]).strength == "not_enough_data"
    assert spearman(np.arange(30), np.full(30, 5.0)).strength == "not_enough_data"  # nothing varies


def title_rows(with_feature, without_feature, feature_title, plain_title, good=3000.0, bad=300.0):
    rows = []
    for i in range(with_feature):
        rows.append({"age": 100 + i, "views": good + i, "title": f"{feature_title} {i}"})
    for i in range(without_feature):
        rows.append({"age": 100 + i, "views": bad + i, "title": f"{plain_title} {i}"})
    return rows


def with_titles(rows):
    frame = make_frame(rows)
    frame[TITLE] = [r.get("title", "") for r in rows]
    return Context(frame, {}, AS_OF, "lifetime")


def test_a_planted_title_effect_survives_the_correction():
    f = title_features(with_titles(title_rows(30, 30, "Is this real?", "A plain title")))

    assert "a question mark" in f.headline and "higher" in f.headline
    question = next(r for r in f.details["features"] if r["feature"] == "a question mark")
    assert question["p_adjusted"] < 0.01 and question["strength"] == "solid"


def test_titles_with_no_effect_do_not_produce_a_finding():
    rng = np.random.default_rng(5)
    rows = [{"age": 100 + i, "views": float(v), "title": ("Why? " if i % 2 else "So ") + f"{i}"}
            for i, v in enumerate(rng.lognormal(7, 0.5, 60))]

    f = title_features(with_titles(rows))

    assert f.headline.startswith("No title feature shows a reliable difference") and f.strength == "weak"


def test_title_features_with_one_sided_data_are_skipped_not_invented():
    f = title_features(with_titles(title_rows(2, 40, "Why?", "Plain")))

    question = next(r for r in f.details["features"] if r["feature"] == "a question mark")
    assert question["p_value"] is None and question["strength"] == "not_enough_data"


def test_duration_effect_finds_a_planted_link_within_long_form():
    # age is made unrelated to length, so the only planted link is length -> views
    rows = [{"age": 100 + (i * 13) % 40, "duration": 200 + 20 * i, "views": 100 + 15 * i} for i in range(40)]

    f = duration_effect(ctx(rows))

    long = next(r for r in f.details["formats"] if r["format"] == "Long-form")
    assert long["rho"] > 0.9 and "longer videos tend to do better" in f.headline


def test_duration_effect_says_no_clear_link_for_noise():
    rng = np.random.default_rng(6)
    rows = [{"age": 100 + i, "duration": int(d), "views": float(v)} for i, (d, v) in enumerate(
            zip(rng.integers(200, 1500, 40), rng.lognormal(6, 0.6, 40), strict=True))]

    assert duration_effect(ctx(rows)).headline.startswith("No clear link")


def test_retention_flags_well_viewed_videos_people_leave_early_and_keeps_formats_apart():
    rows = [{"views": 1000, RETENTION: 60.0, "duration": 600}] * 12
    rows += [{"views": 9000, RETENTION: 12.0, "duration": 600}]  # watched a lot, abandoned early
    rows += [{"views": 500, RETENTION: 105.0, "duration": 30}] * 8  # Shorts replay: over 100% is normal

    frame = make_frame(rows)
    frame[RETENTION] = [r[RETENTION] for r in rows]
    f = retention(Context(frame, {}, AS_OF, "lifetime"))

    assert f.details["by_format"]["Shorts"]["median_percent_viewed"] == 105.0
    assert f.details["candidates"][0]["views"] == 9000
    assert retention(ctx([{"views": 5}] * 3)).strength == "not_enough_data"


# ── the report ──────────────────────────────────────────────────────────────


def sample_audit(title="Normal video"):
    findings = run_audit(Context(make_frame([{"age": 40 + i * 9, "views": 100 + i, "impressions": 9000, "ctr": 4.0}
                                             for i in range(20)]), {}, AS_OF, "lifetime"))
    for f in findings:
        for rows in (f.details.get("best"), f.details.get("candidates")):
            for r in rows or []:
                r["title"] = title
    return {"videos": 20, "as_of": AS_OF, "as_of_source": "test", "findings": [f.__dict__ for f in findings]}


def test_report_is_self_contained_and_has_every_finding():
    html = render_html(sample_audit(), "Acme")

    assert html.startswith("<!doctype html>") and "<script" not in html and "http" not in html.split("<style>")[0]
    assert html.count("<section>") == 8 and "Channel audit: Acme" in html and "Normal video" in html


def test_report_escapes_hostile_titles_and_client_names():
    hostile = '<script>alert("x")</script><img src=x onerror=alert(1)>'

    html = render_html(sample_audit(title=hostile), hostile)

    assert "<script" not in html and "<img" not in html and "&lt;script&gt;" in html


def test_report_route_is_a_locked_down_download(api, tmp_path):
    client_id = upload_channel(api, tmp_path, PROFILES[0])

    response = api.get(f"/api/clients/{client_id}/audit/report")

    assert response.status_code == 200 and response.headers["content-type"].startswith("text/html")
    assert "attachment" in response.headers["content-disposition"] and "audit-pixel-harbor" in response.headers[
        "content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert "Shorts and long-form" in response.text and "Title features" in response.text
    assert api.get(f"/api/clients/{uuid.uuid4()}/audit/report").status_code == 404


def test_videos_all_the_same_age_cannot_be_age_adjusted():
    assert performance(ctx([{"age": 120, "views": 100 + i} for i in range(20)])).strength == "not_enough_data"
