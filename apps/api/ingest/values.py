"""Turning the messy cell values of a Studio export into clean numbers, dates and periods.

An export is read from Excel (typed cells: numbers, datetimes, times) or CSV (everything is text),
so each parser accepts both. "Not reported" is always None, never zero: a blank cell means the
creator's export had no figure, and a stored 0 would claim there was a real zero.
"""
import datetime
import math
import re
from decimal import Decimal
from numbers import Real

import pandas as pd

_THOUSANDS = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")
_CLOCK = re.compile(r"^(\d+):(\d{1,2})(?::(\d{1,2}(?:\.\d+)?))?$")
_ISO_DATE = r"(\d{4}-\d{2}-\d{2})"
_FILENAME_PERIOD = re.compile(rf"{_ISO_DATE}\s*(?:_|-|to|–)\s*{_ISO_DATE}")


def is_blank(value: object) -> bool:
    """True for None, NaN/NaT and empty or whitespace-only text."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _finite(number: float) -> float | None:
    return number if math.isfinite(number) else None


def parse_duration_seconds(value: object) -> float | None:
    """Seconds from an Excel time, a timedelta, "H:MM:SS" / "M:SS" text, or a plain number."""
    if is_blank(value) or isinstance(value, bool):
        return None
    if isinstance(value, datetime.timedelta):
        return value.total_seconds()
    if isinstance(value, datetime.datetime):  # Excel times can arrive as 1899-12-30 plus a time of day
        value = value.time()
    if isinstance(value, datetime.time):
        return value.hour * 3600 + value.minute * 60 + value.second + value.microsecond / 1e6
    if isinstance(value, str):
        match = _CLOCK.match(value.strip())
        if match:
            first, second, third = match.groups()
            if third is None:  # "M:SS"
                return int(first) * 60 + int(second)
            return int(first) * 3600 + int(second) * 60 + float(third)
    return parse_number(value)


def parse_number(value: object) -> float | None:
    """A finite float from a number or numeric text ("1,234", "4.75%"), else None."""
    if is_blank(value) or isinstance(value, bool):
        return None
    if isinstance(value, Real | Decimal):  # Real also covers numpy integers and floats
        return _finite(float(value))
    if isinstance(value, str):
        text = value.strip().rstrip("%").strip()
        if _THOUSANDS.match(text):
            text = text.replace(",", "")
        try:
            return _finite(float(text))
        except ValueError:
            return None
    return None


def parse_metric_value(value: object) -> float | None:
    """A metric cell as a float. Time-like cells (average view duration) become seconds."""
    if isinstance(value, datetime.time | datetime.timedelta | datetime.datetime):
        return parse_duration_seconds(value)
    if isinstance(value, str) and _CLOCK.match(value.strip()):
        return parse_duration_seconds(value)
    return parse_number(value)


def parse_date(value: object) -> datetime.date | None:
    """A calendar date from an Excel date, a timestamp or text; None if it cannot be read."""
    if is_blank(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.date()


def parse_period_from_filename(filename: str) -> tuple[datetime.date, datetime.date] | None:
    """A date range written in the file name, such as "Table data 2026-01-01_2026-03-31.xlsx".

    This relies on Studio including the range in the downloaded file's name, which has not been
    confirmed for every export type, so a result is recorded with source "filename" and can be
    corrected by the user.
    """
    match = _FILENAME_PERIOD.search(filename)
    if not match:
        return None
    try:
        start, end = (datetime.date.fromisoformat(part) for part in match.groups())
    except ValueError:
        return None
    return (start, end) if start <= end else None
