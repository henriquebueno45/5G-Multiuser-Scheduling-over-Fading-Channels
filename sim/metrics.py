"""Per-class and per-user metrics from a SimResult.

Packets arriving in the warm-up or in the final `tail` slots are excluded (the tail must cover the
longest deadline so no counted packet is still pending). Definitions:
    loss        dropped / offered packets
    delay       mean and 95th percentile of delivered packets, in ms (1 slot = 1 ms)
    jitter      mean |delay_i - delay_(i-1)| over consecutive delivered packets of the same user
    throughput  delivered bits per second
    starvation  fraction of slots with queued data but zero PRBs for the class, and the longest
                such run in ms
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from sim.engine import SimResult
from sim.traffic import CLASSES

SLOT_MS = 1.0


def jain(x) -> float:
    x = np.asarray(x, dtype=float)
    return float(x.sum() ** 2 / (len(x) * (x**2).sum())) if len(x) and (x**2).sum() > 0 else 1.0


def _longest_run(flags: np.ndarray) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def _window(res: SimResult, warmup: int, tail: int) -> pd.DataFrame:
    p = res.packets
    return p[(p.arrival >= warmup) & (p.arrival < res.n_slots - tail) & (p.status != "pending")]


def per_class(res: SimResult, warmup: int = 1000, tail: int = 500) -> pd.DataFrame:
    p = _window(res, warmup, tail)
    secs = (res.n_slots - tail - warmup) * SLOT_MS / 1000.0
    rows = []
    for c, name in enumerate(CLASSES):
        g = p[p.cls == c]
        d = g[g.status == "delivered"]
        jit = []
        for _, gu in d.sort_values("arrival").groupby("user"):
            jit.extend(np.abs(np.diff(gu.delay_slots.to_numpy())))
        bl = res.backlogged[c, warmup:res.n_slots - tail]
        starved = bl & (res.prbs[c, warmup:res.n_slots - tail] == 0)
        rows.append({
            "class": name, "offered": len(g), "delivered": len(d),
            "loss": float((g.status == "dropped").mean()) if len(g) else np.nan,
            "delay_mean_ms": float(d.delay_slots.mean() * SLOT_MS) if len(d) else np.nan,
            "delay_p95_ms": float(d.delay_slots.quantile(0.95) * SLOT_MS) if len(d) else np.nan,
            "jitter_ms": float(np.mean(jit) * SLOT_MS) if jit else np.nan,
            "throughput_mbps": float(d.bits.sum() / secs / 1e6),
            "starved_frac": float(starved.sum() / max(bl.sum(), 1)),
            "max_starve_ms": float(_longest_run(starved) * SLOT_MS),
        })
    return pd.DataFrame(rows)


def per_user(res: SimResult, distance_m: np.ndarray, warmup: int = 1000,
             tail: int = 500) -> pd.DataFrame:
    p = _window(res, warmup, tail)
    secs = (res.n_slots - tail - warmup) * SLOT_MS / 1000.0
    rows = []
    for u in range(len(res.user_class)):
        g = p[p.user == u]
        d = g[g.status == "delivered"]
        rows.append({
            "user": u, "class": CLASSES[res.user_class[u]], "distance_m": float(distance_m[u]),
            "offered": len(g), "loss": float((g.status == "dropped").mean()) if len(g) else np.nan,
            "delay_mean_ms": float(d.delay_slots.mean() * SLOT_MS) if len(d) else np.nan,
            "throughput_mbps": float(d.bits.sum() / secs / 1e6),
        })
    return pd.DataFrame(rows)
