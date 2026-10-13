"""Builders for Studio-style export files used across the importer and API tests."""
import csv
import datetime
from pathlib import Path

from openpyxl import Workbook

# The metric columns of a real Studio "Table data" export (the four descriptive columns are not metrics).
STUDIO_METRIC_HEADERS = [
    "Engaged views", "Watch time (hours)", "Subscribers", "Impressions", "Impressions click-through rate (%)",
    "Stayed to watch (%)", "Unique viewers", "Average views per viewer", "New viewers", "Returning viewers",
    "Subscribers gained", "Subscribers lost", "Likes", "Dislikes", "Likes (vs. dislikes) (%)", "Shares",
    "Comments added", "Total sales (USD)", "Orders", "Approved commissions (USD)", "Pending commissions (USD)",
    "Returned products (USD)", "YouTube Premium views", "YouTube Premium watch time (minutes)",
    "Playlist watch time (hours)", "Views from playlist", "Views per playlist start", "Hours streamed",
    "Reminders set", "Chat messages", "Reactions", "Post subscribers", "Remix count", "Remix views",
    "Community clip views", "Watch time from community clips (hours)", "Card clicks", "Cards shown",
    "Clicks per card shown (%)", "Card teaser clicks", "Card teasers shown",
    "Teaser clicks per card teaser shown (%)", "End screen element clicks", "End screen elements shown",
    "Clicks per end screen element shown (%)", "Views", "Average view duration", "Average percentage viewed (%)",
]
DESCRIPTIVE_HEADERS = ["Content", "Video title", "Video publish time", "Duration"]
FULL_HEADERS = DESCRIPTIVE_HEADERS + STUDIO_METRIC_HEADERS

ID_A, ID_B, ID_C = "AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"


def write_xlsx(path: Path, headers: list[str], rows: list[list]) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    return path


def write_csv(path: Path, headers: list[str], rows: list[list]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def simple_rows(total_views: int = 600) -> list[list]:
    """A Total row followed by three videos, for headers [Content, Video title, ..., Duration, Views, Likes]."""
    return [
        ["Total", None, None, None, total_views, 30],
        [ID_A, "First", datetime.datetime(2024, 1, 1), 10, 100, 5],
        [ID_B, "Second", datetime.datetime(2024, 1, 1), 120, 200, 0],
        [ID_C, "Third", datetime.datetime(2024, 1, 3), 600, 300, None],
    ]


SIMPLE_HEADERS = ["Content", "Video title", "Video publish time", "Duration", "Views", "Likes"]


def full_export(path: Path) -> Path:
    """An .xlsx with every column of a real export and synthetic values, including an Excel time cell."""
    def row(content, title, value):
        values = [float(value)] * len(STUDIO_METRIC_HEADERS)
        values[STUDIO_METRIC_HEADERS.index("Average view duration")] = datetime.time(0, 0, 56)
        return [content, title, datetime.datetime(2024, 1, 1), 30, *values]

    rows = [row("Total", None, 30), row(ID_A, "One", 10), row(ID_B, "Two", 20)]
    return write_xlsx(path, FULL_HEADERS, rows)
