"""Strata: band edges, search windows, coverage counting and the scheduler."""
import random
from datetime import timedelta

import pytest
from comment_fakes import NOW

from youtube import strata


@pytest.mark.parametrize(("views", "band"), [
    (0, "<1k"), (999, "<1k"), (1_000, "1k-10k"), (9_999, "1k-10k"), (10_000, "10k-100k"), (99_999, "10k-100k"),
    (100_000, "100k-1M"), (999_999, "100k-1M"), (1_000_000, "1M+"), (50_000_000, "1M+"),
])
def test_view_band_edges(views, band):
    assert strata.view_band(views) == band


@pytest.mark.parametrize(("subscribers", "band"), [
    (None, "hidden"), (0, "<1k"), (999, "<1k"), (1_000, "1k-10k"), (1_000_000, "1M+"),
])
def test_subscriber_band_edges(subscribers, band):
    assert strata.subscriber_band(subscribers) == band


@pytest.mark.parametrize(("days", "band"), [
    (0, "<1mo"), (29, "<1mo"), (30, "1mo-6mo"), (182, "1mo-6mo"), (183, "6mo-1y"), (364, "6mo-1y"),
    (365, "1y-3y"), (1094, "1y-3y"), (1095, "3y+"), (4000, "3y+"),
])
def test_age_band_edges(days, band):
    assert strata.age_band(NOW - timedelta(days=days), NOW) == band


def test_stratum_has_the_four_axes():
    published = NOW - timedelta(days=100)
    assert strata.stratum("20", 5_000, None, published, NOW) == {
        "category_id": "20", "view_band": "1k-10k", "subscriber_band": "hidden", "age_band": "1mo-6mo"}


@pytest.mark.parametrize("band", strata.AGE_BANDS)
def test_a_random_window_lies_inside_its_age_band(band):
    rng = random.Random(1)
    for hours in (2, 72):
        for _ in range(50):
            after, before = strata.random_window(band, NOW, rng, hours)
            assert before - after == timedelta(hours=hours)
            # The window's oldest and youngest ends are both in the band.
            assert strata.age_band(after, NOW) == band and strata.age_band(before - timedelta(seconds=1), NOW) == band


def _row(category_id, view, subscribers, age, videos, comments):
    return {"category_id": category_id, "view_band": view, "subscriber_band": subscribers, "age_band": age,
            "videos": videos, "comments": comments}


def _rows():
    return [
        _row("20", "<1k", "<1k", "<1mo", 2, 40),
        _row("20", "1M+", "1M+", "<1mo", 1, 25),
        _row("27", "<1k", "hidden", "3y+", 1, 10),
    ]


def test_coverage_counts_per_cell_and_per_axis():
    cov = strata.coverage(_rows())

    assert len(cov.cells) == 3
    assert (cov.axes["category_id"]["20"].videos, cov.axes["category_id"]["20"].comments) == (3, 65)
    assert cov.axes["view_band"]["<1k"].comments == 50
    assert cov.axes["subscriber_band"]["hidden"].videos == 1
    assert cov.axes["age_band"]["3y+"].comments == 10
    assert cov.pair("20", "<1mo").comments == 65 and cov.pair("20", "3y+").comments == 0


def test_high_audience_share_is_zero_for_an_empty_band_and_counts_videos():
    cov = strata.coverage(_rows())
    assert cov.high_audience_share("<1mo") == pytest.approx(1 / 3)
    assert cov.high_audience_share("1y-3y") == 0.0


def test_the_scheduler_picks_the_emptiest_pair_first():
    cov = strata.coverage(_rows())
    # Every pair is empty except (20, <1mo) and (27, 3y+); those must come last of all 75.
    order = strata.next_targets(cov, random.Random(0), n=len(strata.CATEGORIES) * len(strata.AGE_BANDS))
    assert order[-2:] == [("27", "3y+"), ("20", "<1mo")]
    assert strata.next_targets(cov, random.Random(0), 3)[0] not in {("20", "<1mo"), ("27", "3y+")}


def test_the_scheduler_is_repeatable_for_a_seed_and_varies_between_seeds():
    cov = strata.coverage([])
    first = strata.next_targets(cov, random.Random(7), 5)
    assert first == strata.next_targets(cov, random.Random(7), 5)
    assert first != strata.next_targets(cov, random.Random(8), 5)


def test_the_scheduler_visits_every_pair_before_repeating_one_and_can_leave_pairs_out():
    cov = strata.coverage([])
    rng = random.Random(3)
    visited = set()
    for _ in range(len(strata.CATEGORIES) * len(strata.AGE_BANDS)):
        category, band = strata.next_targets(cov, rng, 1)[0]
        visited.add((category, band))
        cov.add((category, "<1k", "<1k", band), videos=1, comments=10)  # each visit adds a little
    assert len(visited) == 75  # every pair was reached before any was repeated
    assert strata.next_targets(cov, rng, 1, exclude=visited) == []
