"""Multi-user cell: independent per-user channels -> per-slot spectral efficiency and rate.

Each user is placed uniformly over an annulus (r_min, r_max) around the base station and gets:
    - its own distance (log-distance path loss),
    - its own log-normal shadowing draw (one per user and run),
    - its own small-scale fading (Jakes, L-branch MRC), independent across users.

Per-slot spectral efficiency follows Shannon capacity, SE = min(log2(1 + SNR), SE_MAX), computed
with the reused single-user channel functions. A PRB carries `bits_per_prb` = SE * PRB bandwidth *
slot duration. Per-user random streams come from `SeedSequence.spawn`, so the first k users of a
cell are identical whatever the total number of users.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from channel.channel_model import ChannelConfig, noise_dbm, path_loss_db, rayleigh_power_gain


@dataclass(frozen=True)
class CellConfig:
    n_users: int = 10
    r_min_m: float = 20.0
    r_max_m: float = 300.0
    n_prbs: int = 50  # PRBs available to the cell per slot
    channel: ChannelConfig = field(default_factory=ChannelConfig)  # distance_m is ignored


@dataclass(frozen=True)
class CellRealization:
    distance_m: np.ndarray  # (n_users,)
    shadow_db: np.ndarray  # (n_users,)
    se: np.ndarray  # (n_users, n_slots) bit/s/Hz
    bits_per_prb: np.ndarray  # (n_users, n_slots)


def place_users(n_users: int, r_min: float, r_max: float, rng: np.random.Generator) -> np.ndarray:
    """Distances for users uniform over the annulus area: r^2 ~ U(r_min^2, r_max^2)."""
    return np.sqrt(rng.uniform(r_min**2, r_max**2, n_users))


def generate_cell(n_slots: int, cfg: CellConfig, seed: int = 1) -> CellRealization:
    """Draw one cell realization (positions, shadowing, and fading traces) for `seed`."""
    root = np.random.SeedSequence(seed)
    place_ss, *user_ss = root.spawn(1 + cfg.n_users)
    ch = cfg.channel
    dist = place_users(cfg.n_users, cfg.r_min_m, cfg.r_max_m, np.random.default_rng(place_ss))
    shadow = np.zeros(cfg.n_users)
    se = np.zeros((cfg.n_users, n_slots))
    for u in range(cfg.n_users):
        rng = np.random.default_rng(user_ss[u])
        shadow[u] = rng.normal(0.0, ch.shadow_sigma_db)
        snr_db = np.full(
            n_slots,
            ch.ptx_prb_dbm - path_loss_db(dist[u], replace(ch, distance_m=dist[u])) - shadow[u]
            - noise_dbm(ch),
        )
        if ch.fading:
            snr_db = snr_db + 10 * np.log10(rayleigh_power_gain(n_slots, ch, rng))
        se[u] = np.minimum(np.log2(1 + 10 ** (snr_db / 10)), ch.se_max)
    return CellRealization(dist, shadow, se, se * ch.prb_bw_hz * ch.slot_s)
