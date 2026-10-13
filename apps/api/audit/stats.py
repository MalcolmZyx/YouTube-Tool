"""Small statistics helpers with the honesty built in: every comparison reports its sample sizes and an interval.

Everything here is seeded, so the same data always gives the same report.
"""
from dataclasses import dataclass

import numpy as np
from scipy import stats

SEED = 20261013
BOOTSTRAP_RESAMPLES = 2000
MIN_PER_GROUP = 5  # below this a comparison is not reported as a finding
SOLID_PER_GROUP = 10  # below this it is flagged as weak evidence whatever the p-value


@dataclass(frozen=True)
class Comparison:
    n_a: int
    n_b: int
    median_a: float
    median_b: float
    ratio: float | None  # median_a / median_b
    ratio_low: float | None  # 95% bootstrap interval for the ratio
    ratio_high: float | None
    p_value: float | None  # Mann-Whitney U, two-sided
    effect: float | None  # rank-biserial correlation: -1..1, 0 = no difference, +1 = every a beats every b
    strength: str  # "solid" | "suggestive" | "weak" | "not_enough_data"


def _median_ratio_interval(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    rng = np.random.default_rng(SEED)
    ratios = np.empty(BOOTSTRAP_RESAMPLES)
    for i in range(BOOTSTRAP_RESAMPLES):
        mb = np.median(rng.choice(b, size=b.size))
        ratios[i] = np.median(rng.choice(a, size=a.size)) / mb if mb else np.nan
    low, high = np.nanpercentile(ratios, [2.5, 97.5])
    return float(low), float(high)


def compare(a, b) -> Comparison:
    """Compare two groups of values (for example views of Shorts against long-form videos)."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    n_a, n_b = a.size, b.size
    if min(n_a, n_b) < MIN_PER_GROUP:
        return Comparison(n_a, n_b, float(np.median(a)) if n_a else np.nan, float(np.median(b)) if n_b else np.nan,
                          None, None, None, None, None, "not_enough_data")

    median_a, median_b = float(np.median(a)), float(np.median(b))
    u = stats.mannwhitneyu(a, b, alternative="two-sided")
    effect = 2 * u.statistic / (n_a * n_b) - 1
    ratio = median_a / median_b if median_b else None
    low, high = _median_ratio_interval(a, b) if median_b else (None, None)

    if min(n_a, n_b) < SOLID_PER_GROUP:
        strength = "weak"
    elif u.pvalue < 0.01:
        strength = "solid"
    elif u.pvalue < 0.05:
        strength = "suggestive"
    else:
        strength = "weak"
    return Comparison(n_a, n_b, median_a, median_b, ratio, low, high, float(u.pvalue), float(effect), strength)


def log_linear_fit(x, y) -> tuple[float, float, float]:
    """Least-squares line through (log10(x+1), log10(y+1)). Returns slope, intercept and R squared."""
    lx, ly = np.log10(np.asarray(x, dtype=float) + 1), np.log10(np.asarray(y, dtype=float) + 1)
    slope, intercept = np.polyfit(lx, ly, 1)
    residual = ly - (slope * lx + intercept)
    total = ((ly - ly.mean()) ** 2).sum()
    r_squared = 1 - (residual ** 2).sum() / total if total else 0.0
    return float(slope), float(intercept), float(r_squared)


def holm_adjust(p_values: list[float]) -> list[float]:
    """Holm's step-down correction: p-values adjusted for having tested several things at once."""
    order = sorted(range(len(p_values)), key=lambda i: p_values[i])
    adjusted = [0.0] * len(p_values)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(p_values) - rank) * p_values[i]))
        adjusted[i] = running
    return adjusted


@dataclass(frozen=True)
class Correlation:
    n: int
    rho: float | None  # Spearman rank correlation, -1..1
    low: float | None  # 95% bootstrap interval
    high: float | None
    p_value: float | None
    strength: str


def spearman(x, y) -> Correlation:
    """Rank correlation between two measures, with a bootstrap interval. Blank pairs are dropped."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    keep = ~(np.isnan(x) | np.isnan(y))
    x, y = x[keep], y[keep]
    n = x.size
    if n < MIN_PER_GROUP * 2 or np.ptp(x) == 0 or np.ptp(y) == 0:
        return Correlation(n, None, None, None, None, "not_enough_data")
    result = stats.spearmanr(x, y)
    rng = np.random.default_rng(SEED)
    draws = np.empty(BOOTSTRAP_RESAMPLES)
    for i in range(BOOTSTRAP_RESAMPLES):
        pick = rng.integers(0, n, n)
        draws[i] = stats.spearmanr(x[pick], y[pick]).statistic
    low, high = np.nanpercentile(draws, [2.5, 97.5])
    if n < SOLID_PER_GROUP * 2:
        strength = "weak"
    elif result.pvalue < 0.01:
        strength = "solid"
    elif result.pvalue < 0.05:
        strength = "suggestive"
    else:
        strength = "weak"
    return Correlation(n, float(result.statistic), float(low), float(high), float(result.pvalue), strength)
