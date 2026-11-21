"""Sensitivity of the conclusions to modelling choices (deadlines, DWRR weights, user mix, buffer).

    python -m analysis.sensitivity run --seeds 20 --workers 6
    python -m analysis.sensitivity report

Each variant changes one assumption relative to `base`; results go to results/sens_class.csv
(resumable) and the report writes results/sens_summary.csv and results/sens_loss.png.
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
LOADS = [0.6, 1.0, 1.2, 1.6]
KEY = ["variant", "policy", "load", "seed"]
CLASSES = ["voice", "video", "data"]
# name -> (simulate kwargs, policies it applies to; None = all)
VARIANTS: dict[str, tuple[dict, list[str] | None]] = {
    "base": ({}, None),
    "data_deadline_100ms": ({"deadline_slots": {"data": 100}}, None),
    "data_deadline_2000ms": ({"deadline_slots": {"data": 2000}}, None),
    "voice_deadline_50ms": ({"deadline_slots": {"voice": 50}}, None),
    "dwrr_equal_1_1_1": ({"dwrr_weights": (1, 1, 1)}, ["dwrr"]),
    "dwrr_16_4_1": ({"dwrr_weights": (16, 4, 1)}, ["dwrr"]),
    "mix_6_2_2": ({"mix": (6, 2, 2)}, None),
    "mix_2_4_4": ({"mix": (2, 4, 4)}, None),
    "buffer_5ms": ({"buffer_ms": 5.0}, ["fifobuf"]),
    "buffer_100ms": ({"buffer_ms": 100.0}, ["fifobuf"]),
}


def _job(args):
    variant, policy, load, seed, duration = args
    pc, _, _ = simulate(policy, load, seed, 1, duration_s=duration, **VARIANTS[variant][0])
    return pc.assign(variant=variant, policy=policy, load=load, seed=seed)


def run_sweep(seeds: int, duration: float, workers: int) -> None:
    path = RESULTS / "sens_class.csv"
    done = set()
    if path.exists():
        done = set(map(tuple, pd.read_csv(path, usecols=KEY).drop_duplicates()
                       .itertuples(index=False, name=None)))
    jobs = []
    for seed, load, (v, (_, only)) in itertools.product(range(1, seeds + 1), LOADS,
                                                        VARIANTS.items()):
        for p in only or POLICIES:
            if (v, p, load, seed) not in done:
                jobs.append((v, p, load, seed, duration))
    print(f"{len(jobs)} jobs to run ({len(done)} already done)", flush=True)
    with Pool(workers) as pool:
        for i, df in enumerate(pool.imap_unordered(_job, jobs, chunksize=1), 1):
            df.to_csv(path, mode="a", header=not path.exists(), index=False)
            if i % 100 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)}", flush=True)


def report(load: float) -> None:
    d = pd.read_csv(RESULTS / "sens_class.csv")
    d = d[d.load == load]
    rows = []
    for (v, p, c), g in d.groupby(["variant", "policy", "class"]):
        m, lo, hi = boot_ci(g.loss.to_numpy())
        rows.append({"variant": v, "policy": p, "class": c, "loss": m, "lo": lo, "hi": hi,
                     "n_seeds": g.seed.nunique()})
    s = pd.DataFrame(rows)
    s.to_csv(RESULTS / "sens_summary.csv", index=False)

    # Policies a variant does not touch keep their base values, so every panel shows all five
    base = s[s.variant == "base"]
    fig, axes = plt.subplots(len(CLASSES), 1, figsize=(13, 9), sharex=True)
    names = list(VARIANTS)
    w = 0.16
    colors = {"fifo": "tab:red", "fifobuf": "tab:orange", "prio": "tab:blue",
              "dwrr": "tab:green", "pf": "tab:purple"}
    for ax, c in zip(axes, CLASSES):
        for i, p in enumerate(POLICIES):
            vals, err = [], []
            for v in names:
                g = s[(s.variant == v) & (s.policy == p) & (s["class"] == c)]
                if g.empty:
                    g = base[(base.policy == p) & (base["class"] == c)]
                r = g.iloc[0]
                vals.append(r.loss)
                err.append([r.loss - r.lo, r.hi - r.loss])
            ax.bar(np.arange(len(names)) + (i - 2) * w, vals, w, color=colors[p], label=p,
                   yerr=np.array(err).T, capsize=1.5)
        ax.set_ylabel(f"{c} loss")
        ax.grid(alpha=0.3, axis="y")
    axes[-1].set_xticks(range(len(names)), names, rotation=30, ha="right")
    axes[0].legend(ncol=5)
    fig.suptitle(f"Loss at load {load} under changed assumptions (mean, 95% CI over seeds)")
    fig.tight_layout()
    fig.savefig(RESULTS / "sens_loss.png", dpi=130)
    plt.close(fig)
    piv = s.pivot_table(index=["variant", "class"], columns="policy", values="loss").round(3)
    print(piv.to_string())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--seeds", type=int, default=20)
    r.add_argument("--duration", type=float, default=10.0)
    r.add_argument("--workers", type=int, default=4)
    q = sub.add_parser("report")
    q.add_argument("--load", type=float, default=1.2)
    a = ap.parse_args()
    RESULTS.mkdir(exist_ok=True)
    if a.cmd == "run":
        run_sweep(a.seeds, a.duration, a.workers)
    else:
        report(a.load)


if __name__ == "__main__":
    main()
