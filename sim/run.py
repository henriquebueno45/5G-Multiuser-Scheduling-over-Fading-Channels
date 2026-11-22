"""Run one multi-user simulation and print per-class and per-user metrics.

Example:
    python -m sim.run --policy prio --load 1.2 --seed 1 --antennas 1
"""
from __future__ import annotations

import argparse
from dataclasses import replace

import numpy as np
import pandas as pd

from cell.cell import CellConfig, generate_cell
from channel.channel_model import ChannelConfig
from sim.engine import run
from sim.metrics import per_class, per_user
from sim.policies import POLICIES
from sim.traffic import assign_classes, generate_arrivals, saturation_scale


# Named variants of a base policy: (policy, shared buffer in ms of cell capacity at mean rates).
# "fifobuf" is a conventional FIFO: one finite buffer with tail drop shared by every class.
VARIANTS = {"fifobuf": ("fifo", 20.0)}
POLICY_NAMES = sorted(POLICIES) + sorted(VARIANTS)


def simulate(policy: str, load: float, seed: int, antennas: int = 1, mix=(4, 3, 3),
             duration_s: float = 10.0, cfg: CellConfig | None = None, speed_mps: float = 1.5,
             dwrr_weights=(8, 4, 2), deadline_slots: dict | None = None,
             buffer_ms: float | None = None, cqi_delay_slots: int = 0, backoff_db: float = 0.0):
    """Return (per-class metrics, per-user metrics, SimResult) for one run.

    With `cqi_delay_slots > 0` or `backoff_db > 0` the base station knows the channel only through
    a delayed report: it schedules and transmits at the rate of the reported spectral efficiency
    reduced by `backoff_db`, and a transmission fails if the true channel is worse (see `run`).
    """
    base_policy, variant_buffer = VARIANTS.get(policy, (policy, None))
    buffer_ms = buffer_ms if buffer_ms is not None else variant_buffer
    n_slots = int(duration_s * 1000)
    base = cfg or CellConfig()
    cfg = replace(base, n_users=sum(mix),
                  channel=replace(base.channel, antennas=antennas, speed_mps=speed_mps))
    cell = generate_cell(n_slots, cfg, seed)
    classes = assign_classes(*mix)
    scale = saturation_scale(classes, cell.bits_per_prb.mean(axis=1), cfg.n_prbs)
    arrivals = generate_arrivals(n_slots, classes, scale, load, seed)
    rate_est = None
    if cqi_delay_slots > 0 or backoff_db > 0:
        se = cell.se
        if cqi_delay_slots > 0:
            se = np.concatenate([se[:, :1].repeat(cqi_delay_slots, axis=1),
                                 se[:, :-cqi_delay_slots]], axis=1)
        snr = (2.0 ** se - 1.0) / 10 ** (backoff_db / 10)
        rate_est = np.log2(1 + snr) * cfg.channel.prb_bw_hz * cfg.channel.slot_s
    pol = POLICIES[base_policy](dwrr_weights) if base_policy in ("dwrr", "sliced") else POLICIES[base_policy]()
    buffer_bits = (None if buffer_ms is None
                   else buffer_ms * cfg.n_prbs * float(cell.bits_per_prb.mean()))
    res = run(cell, classes, arrivals, pol, cfg.n_prbs, buffer_bits, deadline_slots, rate_est)
    return per_class(res), per_user(res, cell.distance_m), res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--policy", choices=POLICY_NAMES, default="prio")
    ap.add_argument("--load", type=float, default=1.0, help="relative to saturation (1 = full)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--antennas", type=int, default=1)
    ap.add_argument("--duration", type=float, default=10.0)
    a = ap.parse_args()
    pd.set_option("display.width", 160)
    pc, pu, _ = simulate(a.policy, a.load, a.seed, a.antennas, duration_s=a.duration)
    print(pc.round(3).to_string(index=False))
    print()
    print(pu.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
