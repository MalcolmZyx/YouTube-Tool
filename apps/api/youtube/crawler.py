"""The crawl loop: pick the emptiest part of the corpus, find videos there, read a sample of their comments, repeat.

One round is one search (or chart, or uploads read), one `videos.list`, at most one `channels.list`, and one or two
`commentThreads.list` pages per video. Every video is written to the store as soon as it is read, so a run stopped by
quota or by Ctrl+C loses nothing.
"""
import logging
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

from youtube import comment_store, comments, discovery, strata
from youtube.client import Api, QuotaExceeded, SearchBudgetExhausted
from youtube.discovery import Candidate
from youtube.enrich import MIN_COMMENTS, enrich

logger = logging.getLogger(__name__)

ROUND_CAP = 25  # videos taken from one discovery call, so that one cell is not filled in a single step
MOST_POPULAR_SHARE = 0.1  # share of rounds that read a category's chart instead of searching
MAX_EMPTY_ROUNDS = 20  # rounds in a row with no new video before the run gives up
MAX_MISSES = 2  # fruitless rounds after which a (category, age band) is left alone for the rest of the run


@dataclass
class CrawlSummary:
    videos_kept: int = 0
    comments_kept: int = 0
    rounds: int = 0
    dropped: Counter = field(default_factory=Counter)  # by reason, videos and comments together
    units: dict[str, int] = field(default_factory=dict)  # API requests (= units) by method
    stop_reason: str = ""


class _Crawl:
    def __init__(self, api: Api, seed: int, now: datetime, region: str):
        self.api, self.rng, self.now, self.region = api, random.Random(seed), now, region
        self.search_open = True
        self.channels: list[str] = []  # channels seen, whose uploads can be read when search is closed
        self.expanded: set[str] = set()

    def discover(self, cov: strata.Coverage, category: str, band: str) -> list[Candidate]:
        if self.search_open and self.rng.random() >= MOST_POPULAR_SHARE:
            by_views = band != strata.AGE_BANDS[0] and cov.high_audience_share(band) < strata.HIGH_AUDIENCE_SHARE
            try:
                return discovery.search_window(self.api, category, band, self.now, self.rng, by_views)
            except SearchBudgetExhausted:
                logger.info("Search calls are used up for today; continuing with charts and uploads.")
                self.search_open = False
        found = discovery.most_popular(self.api, category, self.region)
        if not found:
            pending = [c for c in self.channels if c not in self.expanded]
            if pending:
                self.expanded.add(pending[0])
                found = discovery.channel_uploads(self.api, pending[0])
        return found


def _fresh(candidates: list[Candidate], rng: random.Random) -> dict[str, str]:
    """Video ID -> source for a random sample of at most ROUND_CAP candidates, one per channel, none already stored."""
    known = comment_store.known_video_ids(c.video_id for c in candidates)
    pool = [c for c in candidates if c.video_id not in known]
    rng.shuffle(pool)
    chosen: dict[str, str] = {}
    channels: set[str | None] = set()
    for candidate in pool:
        if candidate.video_id in chosen or (candidate.channel_id and candidate.channel_id in channels):
            continue
        channels.add(candidate.channel_id)
        chosen[candidate.video_id] = candidate.source
        if len(chosen) == ROUND_CAP:
            break
    return chosen


def crawl(
    api: Api, videos: int, seed: int, *, max_pages: int = comments.MAX_PAGES,
    per_video_cap: int = comments.PER_VIDEO_CAP, min_comments: int = MIN_COMMENTS, salt: str = "",
    unit_budget: int | None = None, region: str = "US", now: datetime | None = None,
) -> CrawlSummary:
    """Run until `videos` videos are kept, the unit budget or quota is used up, or nothing new can be found.

    `unit_budget` bounds the main-pool units this run may spend (the search bucket is bounded by the Api itself).
    The same seed on the same corpus makes the same choices.
    """
    state = _Crawl(api, seed, now or datetime.now(UTC), region)
    summary = CrawlSummary()
    seen = comment_store.known_dedupe_keys()
    misses: Counter = Counter()
    empty_rounds = 0
    worst_round = 4 + ROUND_CAP * max_pages  # units: chart or uploads (2), videos.list, channels.list, comment pages
    try:
        while summary.videos_kept < videos:
            if unit_budget is not None and unit_budget - api.main_units < worst_round:
                summary.stop_reason = "unit_budget"
                break
            if empty_rounds >= MAX_EMPTY_ROUNDS:
                summary.stop_reason = "no_new_videos"
                break
            cov = strata.coverage(comment_store.coverage_rows())
            exclude = [pair for pair, n in misses.items() if n >= MAX_MISSES]
            targets = strata.next_targets(cov, state.rng, 1, exclude)
            if not targets:
                summary.stop_reason = "no_new_videos"
                break
            category, band = targets[0]
            summary.rounds += 1

            candidates = state.discover(cov, category, band)
            for candidate in candidates:
                if candidate.channel_id and candidate.channel_id not in state.channels:
                    state.channels.append(candidate.channel_id)
            sources = _fresh(candidates, state.rng)
            records, dropped = enrich(api, sources, state.now, min_comments) if sources else ([], Counter())
            summary.dropped.update(dropped)

            kept_before = summary.videos_kept
            for video in records[:videos - summary.videos_kept]:
                result = comments.fetch_comments(
                    api, video, state.rng, seen, state.now, salt, max_pages, per_video_cap)
                comment_store.save_video(video, state.now)
                if result.skipped:
                    summary.dropped[result.skipped] += 1
                    continue
                comment_store.save_comments(result.kept)
                summary.videos_kept += 1
                summary.comments_kept += len(result.kept)
                summary.dropped.update(result.dropped)
            if summary.videos_kept > kept_before:
                empty_rounds = 0
            else:
                empty_rounds += 1
                misses[(category, band)] += 1
        else:
            summary.stop_reason = "target_reached"
    except QuotaExceeded:
        summary.stop_reason = "quota_exceeded"
    summary.units = dict(api.calls)
    return summary
