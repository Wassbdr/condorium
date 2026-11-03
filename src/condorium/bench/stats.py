"""Small, dependency-free statistics for the benches.

n=50 pairs is a small sample: every rate is reported with a seeded bootstrap
95% confidence interval, so a 0.62 is never read as more than it is.
"""

from __future__ import annotations

import random


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def bootstrap_ci(values: list[float], seed: int, n_resamples: int = 1000,
                 alpha: float = 0.05) -> list[float] | None:
    """Percentile bootstrap CI of the mean (deterministic for a given seed)."""
    if not values:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(n_resamples))
    lo = means[int(alpha / 2 * n_resamples)]
    hi = means[int((1 - alpha / 2) * n_resamples) - 1]
    return [round(lo, 3), round(hi, 3)]


def summarize(values: list[float], seed: int) -> dict:
    m = mean(values)
    return {"value": round(m, 3) if m is not None else None,
            "ci95": bootstrap_ci(values, seed), "n": len(values)}


def pair_outcome(winner: object, loser: object) -> float:
    """1 = the real winner is ranked above, 0.5 = tie, 0 = wrong.
    Works on anything comparable (tuples, numbers); None counts as a tie."""
    if winner is None or loser is None or winner == loser:
        return 0.5
    return 1.0 if winner > loser else 0.0
