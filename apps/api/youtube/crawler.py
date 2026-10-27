"""The crawl loop: pick the emptiest part of the corpus, find videos there, read a sample of their comments, repeat.

One round is one search (or chart, or uploads read), one `videos.list`, at most one `channels.list`, and one or two
`commentThreads.list` pages per video. Every video is written to the store as soon as it is read, so a run stopped by
quota or by Ctrl+C loses nothing.

Category and age band can be asked of the API; view and subscriber bands are known only after `videos.list` and
`channels.list`. So a round is steered twice: before the search, by the emptiest (category, age band) pair and the
emptiest view band (which decides how to search); after enrichment and before any comment is read, by a quota that
turns away the videos whose bands, on any axis, are already over their share (`strata.over_quota`).
"""
import logging
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

from youtube import comment_store, comments, discovery, strata
from youtube.client import Api, QuotaExceeded, SearchBudgetExhausted
from youtube.discovery import Candidate
from youtube.enrich import MIN_COMMENTS, VideoRecord, enrich

logger = logging.getLogger(__name__)

CANDIDATE_CAP = 50  # videos looked at from one discovery call: one videos.list, and the quota picks among them
ROUND_CAP = 25  # videos read from one discovery call, so that one cell is not filled in a single step
CHART_SHARE = 0.5  # share of the rounds wanting 1M+ videos that read a chart instead of searching
UPLOADS_SHARE = 0.3  # share of the rounds wanting <10k-view videos that read a small channel's uploads instead
MAX_EMPTY_ROUNDS = 20  # rounds in a row with no new video before the run gives up
MAX_MISSES = 2  # fruitless rounds after which a (category, age band) is left alone for the rest of the run
MAX_VIEW_MISSES = 3  # fruitless rounds in a row after which a view band is not chased any more in this run


@dataclass
class CrawlSummary:
    videos_kept: int = 0
    comments_kept: int = 0
    rounds: int = 0
    dropped: Counter = field(default_factory=Counter)  # by reason, videos and comments together; over_quota_<axis>
    units: dict[str, int] = field(default_factory=dict)  # API requests (= units) by method
    stop_reason: str = ""


class _Crawl:
    def __init__(self, api: Api, seed: int, now: datetime, region: str):
        self.api, self.rng, self.now, self.region = api, random.Random(seed), now, region
        self.search_open = True
        self.channels: list[str] = []  # channels seen, whose uploads can be read when search is closed
        self.small_channels: list[str] = []  # channels seen with under 10k subscribers: their videos are small too
        self.expanded: set[str] = set()

    def _uploads(self, channels: list[str]) -> list[Candidate]:
        pending = [c for c in channels if c not in self.expanded]
        if not pending:
            return []
        self.expanded.add(pending[0])
        return discovery.channel_uploads(self.api, pending[0])

    def discover(self, category: str, band: str, view_band: str | None) -> list[Candidate]:
        """Find candidates the way that suits the view band the corpus lacks most: the uploads of small channels or a
        date-ordered search for the low bands, a view-count search for the high ones, the chart for the top one."""
        if view_band in strata.LOW_VIEW_BANDS and (not self.search_open or self.rng.random() < UPLOADS_SHARE):
            if found := self._uploads(self.small_channels):
                return found
        top = view_band == strata.VIEW_BANDS[-1]
        if self.search_open and not (top and self.rng.random() < CHART_SHARE):
            try:
                return discovery.search_window(
                    self.api, category, band, self.now, self.rng, view_band in strata.HIGH_VIEW_BANDS)
            except SearchBudgetExhausted:
                logger.info("Search calls are used up for today; continuing with charts and uploads.")
                self.search_open = False
        return discovery.most_popular(self.api, category, self.region) or self._uploads(self.channels)


def _fresh(candidates: list[Candidate], rng: random.Random) -> dict[str, str]:
    """Video ID -> source for a random sample of at most CANDIDATE_CAP candidates, one per channel, none stored."""
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
        if len(chosen) == CANDIDATE_CAP:
            break
    return chosen


def _within_quota(records: list[VideoRecord], cov: strata.Coverage, dropped: Counter) -> list[VideoRecord]:
    """The records whose bands are not over their share, in order; each one taken counts towards the next one's share.
    The others are counted in `dropped` as over_quota_<axis>."""
    wanted = []
    for record in records:
        if axis := strata.over_quota(cov, record.stratum):
            dropped[f"over_quota_{axis}"] += 1
            continue
        cov.add(tuple(record.stratum[a] for a in strata.AXES), videos=1)
        wanted.append(record)
    return wanted


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
    state.small_channels = comment_store.channel_ids(strata.LOW_SUBSCRIBER_BANDS)
    state.rng.shuffle(state.small_channels)
    summary = CrawlSummary()
    seen = comment_store.known_dedupe_keys()
    misses: Counter = Counter()
    view_misses: Counter = Counter()
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
            chased = [b for b, n in view_misses.items() if n >= MAX_VIEW_MISSES]
            view_band = strata.next_view_band(cov, state.rng, chased)
            summary.rounds += 1

            candidates = state.discover(category, band, view_band)
            for candidate in candidates:
                if candidate.channel_id and candidate.channel_id not in state.channels:
                    state.channels.append(candidate.channel_id)
            sources = _fresh(candidates, state.rng)
            records, dropped = enrich(api, sources, state.now, min_comments) if sources else ([], Counter())
            summary.dropped.update(dropped)
            for record in records:
                if record.stratum["subscriber_band"] in strata.LOW_SUBSCRIBER_BANDS \
                        and record.channel_id not in state.small_channels:
                    state.small_channels.append(record.channel_id)
            wanted = _within_quota(records, cov, summary.dropped)

            kept_before = summary.videos_kept
            kept_bands: Counter = Counter()
            for video in wanted[:min(ROUND_CAP, videos - summary.videos_kept)]:
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
                kept_bands[video.stratum["view_band"]] += 1
            if view_band:
                view_misses[view_band] = 0 if kept_bands[view_band] else view_misses[view_band] + 1
            if summary.videos_kept > kept_before:
                empty_rounds = 0
            else:
                empty_rounds += 1
                if not candidates or any(c.source != discovery.UPLOADS for c in candidates):
                    misses[(category, band)] += 1
        else:
            summary.stop_reason = "target_reached"
    except QuotaExceeded:
        summary.stop_reason = "quota_exceeded"
    summary.units = dict(api.calls)
    return summary
