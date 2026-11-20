"""Statistics helpers reused from the single-user scheduler simulator (tag v1.0).

Source: Traffic-Scheduling-with-QoS-in-a-Congested-5G-Base-Station, analysis/exp_report.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RNG = np.random.default_rng(0)
SLA = 0.99


def boot_ci(x, n_boot: int = 2000) -> tuple[float, float, float]:
    """Return (mean, lower bound, upper bound) using a 95% bootstrap percentile interval."""
    v = np.asarray(x, dtype=float)
    v = v[~np.isnan(v)]
    if len(v) == 0:
        return (np.nan,) * 3
    m = RNG.choice(v, size=(n_boot, len(v)), replace=True).mean(axis=1)
    return float(v.mean()), *map(float, np.percentile(m, [2.5, 97.5]))


def paired_ci(a: pd.Series, b: pd.Series) -> tuple[float, float, float]:
    """Confidence interval for the mean of (a - b), paired by seed index."""
    j = pd.concat([a, b], axis=1, join="inner").dropna()
    return boot_ci((j.iloc[:, 0] - j.iloc[:, 1]).to_numpy())


def sla_capacity(loads: np.ndarray, m: np.ndarray, thr: float = SLA) -> tuple[float, str]:
    """Load where the metric `m` crosses `thr` by linear interpolation.

    Returns (capacity, status): 'ok', 'left' (violates at the lowest load), or
    'right' (never violates; censored at the highest load).
    """
    if m[0] < thr:
        return float(loads[0]), "left"
    for i in range(1, len(loads)):
        if m[i] < thr:
            x = loads[i - 1] + (m[i - 1] - thr) / (m[i - 1] - m[i]) * (loads[i] - loads[i - 1])
            return float(x), "ok"
    return float(loads[-1]), "right"
