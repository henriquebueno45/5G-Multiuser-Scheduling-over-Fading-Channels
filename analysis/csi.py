"""Imperfect channel knowledge: stale CQI reports and link-adaptation back-off.

The base station knows each user's spectral efficiency only through a report `delay` ms old and
transmits at that rate reduced by `backoff` dB; if the true channel is worse the transmission
fails and its PRBs are wasted (the bits stay queued and are sent again). This tests whether the
policy conclusions of the perfect-CSI study survive. Perfect CSI is the reference variant.

    python -m analysis.csi run --seeds 20 --workers 6
    python -m analysis.csi report

Results: results/csi_class.csv (resumable), results/csi_summary.csv and results/csi_loss.png.
"""
from __future__ import annotations

import argparse
import itertools
from multiprocessing import Pool

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from analysis.experiments import RESULTS  # noqa: E402
from analysis.stats import boot_ci  # noqa: E402
from sim.run import simulate  # noqa: E402

POLICIES = ["fifo", "fifobuf", "prio", "dwrr", "pf"]
LOADS = [0.8, 1.2]
ANTENNAS = [1, 4]
SPEEDS = [1.5, 15.0]  # m/s: pedestrian and vehicular
CLASSES = ["voice", "video", "data"]
# name -> (CQI delay in ms, back-off in dB)
CSI = {"perfect": (0, 0.0), "d5_b0": (5, 0.0), "d5_b3": (5, 3.0), "d5_b6": (5, 6.0),
       "d10_b6": (10, 6.0)}
KEY = ["speed", "csi", "policy", "load", "antennas", "seed"]


def _job(args):
    speed, csi, policy, load, antennas, seed, duration = args
    delay, backoff = CSI[csi]
    pc, _, _ = simulate(policy, load, seed, antennas, duration_s=duration, speed_mps=speed,
                        cqi_delay_slots=delay, backoff_db=backoff)
    return pc.assign(speed=speed, csi=csi, policy=policy, load=load, antennas=antennas, seed=seed)


def run_sweep(seeds: int, duration: float, workers: int) -> None:
    path = RESULTS / "csi_class.csv"
    done = set()
    if path.exists():
        done = set(map(tuple, pd.read_csv(path, usecols=KEY).drop_duplicates()
                       .itertuples(index=False, name=None)))
    jobs = [(v, c, p, l, k, s, duration)
            for s, v, c, l, k, p in itertools.product(range(1, seeds + 1), SPEEDS, CSI, LOADS,
                                                      ANTENNAS, POLICIES)
            if (v, c, p, l, k, s) not in done]
    print(f"{len(jobs)} jobs to run ({len(done)} already done)", flush=True)
    with Pool(workers) as pool:
        for i, df in enumerate(pool.imap_unordered(_job, jobs, chunksize=1), 1):
            df.to_csv(path, mode="a", header=not path.exists(), index=False)
            if i % 100 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)}", flush=True)


def report(load: float, antennas: int) -> None:
    d = pd.read_csv(RESULTS / "csi_class.csv")
    rows = []
    for (v, c, p, k, l, cl), g in d.groupby(["speed", "csi", "policy", "antennas", "load",
                                             "class"]):
        row = {"speed": v, "csi": c, "policy": p, "antennas": k, "load": l, "class": cl,
               "n_seeds": g.seed.nunique()}
        for m in ("loss", "bler", "throughput_mbps"):
            row[m], row[m + "_lo"], row[m + "_hi"] = boot_ci(g[m].to_numpy())
        rows.append(row)
    s = pd.DataFrame(rows)
    s.to_csv(RESULTS / "csi_summary.csv", index=False)
    sel = s[(s.load == load) & (s.antennas == antennas)]

    fig, axes = plt.subplots(len(CLASSES), len(SPEEDS), figsize=(13, 9), sharex=True, sharey="row")
    colors = {"fifo": "tab:red", "fifobuf": "tab:orange", "prio": "tab:blue",
              "dwrr": "tab:green", "pf": "tab:purple"}
    w = 0.16
    for j, v in enumerate(SPEEDS):
        for i, c in enumerate(CLASSES):
            ax = axes[i, j]
            for q, p in enumerate(POLICIES):
                g = sel[(sel.speed == v) & (sel.policy == p) & (sel["class"] == c)]
                g = g.set_index("csi").reindex(list(CSI))
                ax.bar(np.arange(len(CSI)) + (q - 2) * w, g.loss, w, color=colors[p], label=p,
                       yerr=[g.loss - g.loss_lo, g.loss_hi - g.loss], capsize=1.5)
            if i == 0:
                ax.set_title(f"{v:g} m/s")
            if j == 0:
                ax.set_ylabel(f"{c} loss")
            ax.grid(alpha=0.3, axis="y")
    for ax in axes[-1]:
        ax.set_xticks(range(len(CSI)), list(CSI))
        ax.set_xlabel("channel knowledge (delay ms, back-off dB)")
    axes[0, 0].legend(ncol=5)
    fig.suptitle(f"Loss under imperfect CSI, load {load}, L={antennas}")
    fig.tight_layout()
    fig.savefig(RESULTS / "csi_loss.png", dpi=130)
    plt.close(fig)

    b = sel[sel["class"] == "voice"].pivot_table(index=["speed", "csi"], columns="policy",
                                                values="bler")
    print("Transmission failure rate (BLER):")
    print(b.round(3).to_string())
    print(f"\nLoss at load {load}, L={antennas}:")
    print(sel.pivot_table(index=["speed", "csi", "class"], columns="policy",
                          values="loss").round(3).to_string())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--seeds", type=int, default=20)
    r.add_argument("--duration", type=float, default=10.0)
    r.add_argument("--workers", type=int, default=4)
    q = sub.add_parser("report")
    q.add_argument("--load", type=float, default=1.2)
    q.add_argument("--antennas", type=int, default=1)
    a = ap.parse_args()
    RESULTS.mkdir(exist_ok=True)
    if a.cmd == "run":
        run_sweep(a.seeds, a.duration, a.workers)
    else:
        report(a.load, a.antennas)


if __name__ == "__main__":
    main()
