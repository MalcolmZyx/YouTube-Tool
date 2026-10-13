"""Generate a fake channel's Studio "Table data" export.

Same seed, same file. The shapes are chosen to resemble what a real export showed: heavy-tailed views, Shorts
without impressions, subscribers partly credited to the channel rather than to videos, a Total row first, and
many columns that are zero for most channels.
"""
import datetime
import string
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from openpyxl import Workbook

# Column order of a real export. The four descriptive columns come first, then the metrics.
HEADERS = [
    "Content", "Video title", "Video publish time", "Duration",
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
EXPORTED_ON = datetime.date(2026, 10, 1)  # fixed, so the output never depends on today's date
_ID_ALPHABET = list(string.ascii_letters + string.digits + "-_")

_TOPICS = ["Retro platformers", "Speedrun tips", "Indie game reviews", "Level design", "Pixel art",
           "Game jam diary", "Sound design", "Boss fights", "Roguelike builds", "Cozy games"]
_FORMATS = ["{t}: what nobody tells you", "I tried {t} for 30 days", "{t} in 60 seconds", "Why {t} matters",
            "{t}: the full guide", "Ranking every {t} idea", "{t} mistakes to avoid", "Is {t} dead?"]


@dataclass(frozen=True)
class ChannelProfile:
    name: str
    seed: int
    videos: int
    shorts_share: float  # fraction of uploads that are Shorts
    median_views: float  # of a long-form video once it has matured
    ctr: float  # typical impressions click-through rate, as a fraction
    years: float = 2.0  # how far back the channel's uploads reach


PROFILES = [
    ChannelProfile("Pixel Harbor", seed=11, videos=60, shorts_share=0.45, median_views=1800, ctr=0.055),
    ChannelProfile("Quiet Orbit Studio", seed=22, videos=30, shorts_share=0.1, median_views=420, ctr=0.04),
    ChannelProfile("Nightshift Gamer", seed=33, videos=110, shorts_share=0.7, median_views=9000, ctr=0.07),
]


def _video_id(rng: np.random.Generator, used: set[str]) -> str:
    while True:
        candidate = "".join(rng.choice(_ID_ALPHABET, size=11))
        if candidate not in used:
            used.add(candidate)
            return candidate


def _video(rng: np.random.Generator, profile: ChannelProfile, used: set[str]) -> dict:
    is_short = rng.random() < profile.shorts_share
    age_days = int(rng.integers(3, int(profile.years * 365)))
    published = EXPORTED_ON - datetime.timedelta(days=age_days)
    duration = int(rng.integers(15, 58)) if is_short else int(rng.integers(180, 1500))

    # Heavy-tailed popularity; young videos have not collected all their views yet.
    popularity = rng.lognormal(mean=0.0, sigma=1.1 if is_short else 0.8)
    matured = 1 - np.exp(-age_days / 30)
    views = int(profile.median_views * (1.6 if is_short else 1.0) * popularity * matured)

    pct_viewed = rng.uniform(0.55, 1.05) if is_short else rng.uniform(0.25, 0.55)
    impressions = None if is_short else max(int(views / max(rng.normal(profile.ctr, profile.ctr * 0.25), 0.01)), 1)
    gained = int(views * rng.uniform(0.0005, 0.004))
    topic = _TOPICS[int(rng.integers(len(_TOPICS)))]
    title = _FORMATS[int(rng.integers(len(_FORMATS)))].format(t=topic)
    return {
        "id": _video_id(rng, used), "title": title, "published": published, "duration": duration,
        "views": views, "engaged": int(views * (rng.uniform(0.3, 0.7) if is_short else rng.uniform(0.6, 0.9))),
        "avg_duration": duration * pct_viewed, "pct_viewed": pct_viewed * 100, "impressions": impressions,
        "ctr": None if impressions is None else views / impressions * 100,
        "gained": gained, "lost": int(gained * rng.uniform(0, 0.25)),
        "likes": int(views * rng.uniform(0.01, 0.06)), "shares": int(views * rng.uniform(0.0005, 0.006)),
        "comments": int(views * rng.uniform(0.0002, 0.003)),
    }


def _seconds_as_time(seconds: float) -> datetime.time:
    whole = int(round(seconds))
    return datetime.time(whole // 3600, whole % 3600 // 60, whole % 60)


def _row(values: dict) -> list:
    """Place named values into the full column order; unused columns are 0, like a channel without that feature."""
    row = dict.fromkeys(HEADERS, 0)
    row.update(values)
    return [row[h] for h in HEADERS]


def generate_rows(profile: ChannelProfile) -> list[list]:
    """The Total row followed by one row per video, most viewed first, in Studio's column order."""
    rng = np.random.default_rng(profile.seed)
    used: set[str] = set()
    videos = sorted((_video(rng, profile, used) for _ in range(profile.videos)), key=lambda v: -v["views"])

    rows = []
    for v in videos:
        hours = v["views"] * v["avg_duration"] / 3600
        rows.append(_row({
            "Content": v["id"], "Video title": v["title"],
            "Video publish time": datetime.datetime.combine(v["published"], datetime.time()),
            "Duration": v["duration"], "Views": v["views"], "Engaged views": v["engaged"],
            "Watch time (hours)": round(hours, 4), "Impressions": v["impressions"],
            "Impressions click-through rate (%)": v["ctr"],
            "Subscribers": v["gained"] - v["lost"], "Subscribers gained": v["gained"],
            "Subscribers lost": v["lost"], "Likes": v["likes"], "Shares": v["shares"],
            "Comments added": v["comments"], "Average view duration": _seconds_as_time(v["avg_duration"]),
            "Average percentage viewed (%)": round(v["pct_viewed"], 2),
        }))

    def total(key):
        return sum(v[key] for v in videos)

    views = total("views")
    hours = sum(v["views"] * v["avg_duration"] for v in videos) / 3600
    impressions = sum(v["impressions"] or 0 for v in videos)
    long_views = sum(v["views"] for v in videos if v["impressions"])
    # Like the real export, subscribers are partly credited to the channel, so the Total exceeds the video sum.
    channel_gained = int(total("gained") * 1.8) + 5
    channel_lost = int(total("lost") * 1.3) + 1
    total_row = _row({
        "Content": "Total", "Views": views, "Engaged views": total("engaged"),
        "Watch time (hours)": round(hours, 4), "Impressions": impressions,
        "Impressions click-through rate (%)": round(long_views / impressions * 100, 2) if impressions else None,
        "Subscribers": channel_gained - channel_lost, "Subscribers gained": channel_gained,
        "Subscribers lost": channel_lost, "Likes": total("likes"), "Shares": total("shares"),
        "Comments added": total("comments"), "Unique viewers": int(views * 0.62),
        "Average view duration": _seconds_as_time(hours * 3600 / max(views, 1)),
    })
    return [total_row, *rows]


def write_export(profile: ChannelProfile, directory: Path) -> Path:
    """Write the profile's export as an .xlsx whose name carries the date range, as Studio's downloads do."""
    start = EXPORTED_ON - datetime.timedelta(days=int(profile.years * 365))
    path = directory / f"{profile.name} Table data {start.isoformat()}_{EXPORTED_ON.isoformat()}.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Table data"
    sheet.append(HEADERS)
    for row in generate_rows(profile):
        sheet.append(row)
    workbook.save(path)
    return path
