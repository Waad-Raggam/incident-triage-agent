"""Window features for the anomaly model. Pure Python (no numpy) so the drift Lambda can import it too.

A window is a metric series, oldest -> newest. The last 3 points are "recent", the rest is the baseline.
The question the model answers: does the recent part look unlike the baseline?
"""

from __future__ import annotations

import math
import statistics

RECENT = 3
Z_CLIP = 50.0
FEATURE_NAMES = ["z_max_recent", "z_min_recent", "z_mean_recent", "log_ratio_recent", "n_recent_high", "baseline_cv"]


def _clip(x: float) -> float:
    return max(-Z_CLIP, min(Z_CLIP, x))


def window_features(values: list[float]) -> list[float]:
    if len(values) < RECENT + 3:
        raise ValueError(f"need at least {RECENT + 3} values")
    baseline, recent = values[:-RECENT], values[-RECENT:]
    med = statistics.median(baseline)
    mad = statistics.median([abs(v - med) for v in baseline])
    # Floors: 5% of the median (quiet latency series) and 1.0 (error counts that are usually 0).
    # Our metrics are counts or milliseconds, so 1.0 is a sensible absolute floor.
    scale = max(1.4826 * mad, 0.05 * abs(med), 1.0)
    z = [(v - med) / scale for v in recent]
    mean_recent = sum(recent) / RECENT
    cv = (statistics.pstdev(baseline) / abs(med)) if abs(med) > 1e-9 else 0.0
    return [
        _clip(max(z)),
        _clip(min(z)),  # catches drops, e.g. traffic falling off a cliff
        _clip(sum(z) / RECENT),
        math.log1p(max(mean_recent, 0)) - math.log1p(max(med, 0)),
        float(sum(1 for x in z if abs(x) > 3)),
        min(cv, 10.0),
    ]
