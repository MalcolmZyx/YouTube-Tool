"""Cell parsers. Pure functions, so these need no database."""
import datetime

import numpy as np
import pandas as pd
import pytest

from ingest.values import (
    is_blank,
    parse_date,
    parse_duration_seconds,
    parse_metric_value,
    parse_number,
    parse_period_from_filename,
)


@pytest.mark.parametrize("value", [None, "", "   ", float("nan"), pd.NaT, np.nan, pd.NA])
def test_blank_values(value):
    assert is_blank(value)


@pytest.mark.parametrize("value", [0, 0.0, "0", "x", False, datetime.time(0, 0)])
def test_zero_and_text_are_not_blank(value):
    assert not is_blank(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5, 5.0), (4.75, 4.75), (np.int64(7), 7.0), (np.float64(1.5), 1.5),
        ("12", 12.0), (" 4.75 ", 4.75), ("4.75%", 4.75), ("1,234", 1234.0), ("-2", -2.0), ("1,234.5", 1234.5),
        (0, 0.0), ("0", 0.0),
    ],
)
def test_parse_number(value, expected):
    assert parse_number(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None, "", "abc", "12abc", float("nan"), float("inf"), float("-inf"),
        True, False, "1,23", datetime.date(2024, 1, 1),
    ],
)
def test_parse_number_rejects_what_is_not_a_finite_number(value):
    assert parse_number(value) is None


def test_zero_is_a_value_but_blank_is_not():
    """The distinction the whole data model rests on."""
    assert parse_number(0) == 0.0
    assert parse_number("") is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime.time(0, 0, 56), 56),
        (datetime.time(1, 2, 3), 3723),
        (datetime.time(0, 0, 0, 500_000), 0.5),
        (datetime.timedelta(minutes=2, seconds=30), 150),
        (datetime.datetime(1899, 12, 30, 0, 1, 3), 63),
        ("00:00:56", 56),
        ("1:03", 63),  # minutes:seconds
        ("0:01:03", 63),  # hours:minutes:seconds
        ("1:02:03.5", 3723.5),
        (56, 56),
        ("56", 56),
    ],
)
def test_parse_duration_seconds(value, expected):
    assert parse_duration_seconds(value) == expected


@pytest.mark.parametrize("value", [None, "", "later", True])
def test_parse_duration_rejects_nonsense(value):
    assert parse_duration_seconds(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [(datetime.time(0, 0, 12), 12), ("00:00:12", 12), (9294, 9294.0), ("9,294", 9294.0), ("4.75%", 4.75), (None, None)],
)
def test_parse_metric_value_treats_time_cells_as_seconds(value, expected):
    assert parse_metric_value(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime.datetime(2021, 6, 15), datetime.date(2021, 6, 15)),
        (pd.Timestamp("2021-06-15 13:45"), datetime.date(2021, 6, 15)),
        ("2021-06-15", datetime.date(2021, 6, 15)),
        (None, None),
        ("", None),
        ("not a date", None),
    ],
)
def test_parse_date(value, expected):
    assert parse_date(value) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Table data 2026-01-01_2026-03-31.xlsx", (datetime.date(2026, 1, 1), datetime.date(2026, 3, 31))),
        ("Content 2026-01-01 to 2026-03-31 Channel.xlsx", (datetime.date(2026, 1, 1), datetime.date(2026, 3, 31))),
        ("export 2026-01-01-2026-01-01.csv", (datetime.date(2026, 1, 1), datetime.date(2026, 1, 1))),
        ("export.xlsx", None),
        ("export 2026-03-31_2026-01-01.xlsx", None),  # end before start
        ("export 2026-13-01_2026-14-01.xlsx", None),  # impossible dates
        ("export 2026-01-01.xlsx", None),  # a single date is not a range
    ],
)
def test_parse_period_from_filename(name, expected):
    assert parse_period_from_filename(name) == expected
