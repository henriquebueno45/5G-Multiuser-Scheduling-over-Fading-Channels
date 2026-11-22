"""Summaries, paired comparisons and plots from an experiment sweep.

Usage:
    python -m analysis.report --name main
Writes results/<name>_summary.csv, _paired.csv, _capacity.csv, _edge.csv, _fairness.csv and PNG
plots in results/.
"""
from __future__ import annotations

import argparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from analysis.experiments import RESULTS  # noqa: E402
from analysis.stats import boot_ci, paired_ci, sla_capacity  # noqa: E402
from sim.metrics import jain  # noqa: E402

CLASSES = ["voice", "video", "data"]
METRICS = ["loss", "delay_p95_ms", "jitter_ms", "throughput_mbps", "starved_frac"]
COLORS = {"fifo": "tab:red", "prio": "tab:blue", "dwrr": "tab:green", "pf": "tab:purple",
          "fifobuf": "tab:orange", "sliced": "tab:cyan"}
EDGE_M, CENTRE_M = 200.0, 100.0


def summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (p, k, c, l), g in df.groupby(["policy", "antennas", "class", "load"]):
        row = {"policy": p, "antennas": k, "class": c, "load": l, "n_seeds": g.seed.nunique()}
        for m in METRICS:
            row[m], row[m + "_lo"], row[m + "_hi"] = boot_ci(g[m].to_numpy())
        rows.append(row)
    return pd.DataFrame(rows)


def paired(df: pd.DataFrame, pairs, metric: str = "loss") -> pd.DataFrame:
    rows = []
    for (k, c, l), g in df.groupby(["antennas", "class", "load"]):
        w = g.pivot_table(index="seed", columns="policy", values=metric)
        for a, b in pairs:
            if a in w and b in w:
                m, lo, hi = paired_ci(w[a], w[b])
                rows.append({"antennas": k, "class": c, "load": l, "a": a, "b": b,
                             "metric": metric, "diff": m, "lo": lo, "hi": hi,
                             "significant": bool(lo > 0 or hi < 0)})
    return pd.DataFrame(rows)


def capacity(df: pd.DataFrame, thr: float = 0.99) -> pd.DataFrame:
    """Highest load at which a class still delivers >= thr of its packets (per seed, then CI)."""
    rows = []
    for (p, k, c), g in df.groupby(["policy", "antennas", "class"]):
        caps, status = [], []
        for _, gs in g.groupby("seed"):
            gs = gs.sort_values("load")
            x, s = sla_capacity(gs["load"].to_numpy(), 1 - gs["loss"].to_numpy(), thr)
            caps.append(x)
            status.append(s)
        m, lo, hi = boot_ci(caps)
        rows.append({"policy": p, "antennas": k, "class": c, "capacity": m, "lo": lo, "hi": hi,
                     "frac_left_censored": np.mean([s == "left" for s in status]),
                     "frac_right_censored": np.mean([s == "right" for s in status])})
    return pd.DataFrame(rows)


def edge_centre(du: pd.DataFrame) -> pd.DataFrame:
    zone = np.where(du.distance_m < CENTRE_M, "centre",
                    np.where(du.distance_m > EDGE_M, "edge", "mid"))
    du = du.assign(zone=zone)
    du = du[du.zone != "mid"]
    rows = []
    for (p, k, c, l, z), g in du.groupby(["policy", "antennas", "class", "load", "zone"]):
        per_seed = g.groupby("seed").loss.mean()
        m, lo, hi = boot_ci(per_seed.to_numpy())
        rows.append({"policy": p, "antennas": k, "class": c, "load": l, "zone": z,
                     "loss": m, "lo": lo, "hi": hi, "n_seeds": len(per_seed)})
    return pd.DataFrame(rows)


def fairness(du: pd.DataFrame) -> pd.DataFrame:
    """Jain index over users' delivered fractions (1 - loss), computed per seed."""
    d = du.assign(ok=1 - du.loss.fillna(0))
    j = (d.groupby(["policy", "antennas", "load", "seed"]).ok.apply(jain)
         .rename("jain").reset_index())
    rows = []
    for (p, k, l), g in j.groupby(["policy", "antennas", "load"]):
        m, lo, hi = boot_ci(g.jain.to_numpy())
        rows.append({"policy": p, "antennas": k, "load": l, "jain": m, "lo": lo, "hi": hi})
    return pd.DataFrame(rows)


def _band(ax, g, col, color, label, ls="-"):
    g = g.sort_values("load")
    ax.plot(g.load, g[col], color=color, label=label, ls=ls, marker="o", ms=3)
    ax.fill_between(g.load, g[col + "_lo"], g[col + "_hi"], color=color, alpha=0.15)


def plot_policies(s: pd.DataFrame, antennas: int, out) -> None:
    fig, axes = plt.subplots(len(METRICS), 3, figsize=(13, 14), sharex=True)
    for i, m in enumerate(METRICS):
        for j, c in enumerate(CLASSES):
            ax = axes[i, j]
            for p, color in COLORS.items():
                g = s[(s.policy == p) & (s.antennas == antennas) & (s["class"] == c)]
                if len(g):
                    _band(ax, g, m, color, p)
            if i == 0:
                ax.set_title(c)
            if j == 0:
                ax.set_ylabel(m)
            if m == "loss":
                ax.axhline(0.01, color="gray", ls=":", lw=1)
            ax.grid(alpha=0.3)
    for ax in axes[-1]:
        ax.set_xlabel("offered load (1 = saturation)")
    axes[0, 0].legend()
    fig.suptitle(f"Policies, {antennas} antenna(s); mean and 95% bootstrap CI over seeds")
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def plot_diversity(s: pd.DataFrame, out) -> None:
    pols = sorted(s.policy.unique())
    fig, axes = plt.subplots(len(CLASSES), len(pols), figsize=(3.6 * len(pols), 9),
                             sharex=True, sharey="row", squeeze=False)
    cmap = {1: "tab:orange", 2: "tab:cyan", 4: "tab:brown"}
    for j, p in enumerate(pols):
        for i, c in enumerate(CLASSES):
            ax = axes[i, j]
            for k in sorted(s.antennas.unique()):
                g = s[(s.policy == p) & (s.antennas == k) & (s["class"] == c)]
                if len(g):
                    _band(ax, g, "loss", cmap.get(k, "k"), f"L={k}")
            if i == 0:
                ax.set_title(p)
            if j == 0:
                ax.set_ylabel(f"{c} loss")
            ax.axhline(0.01, color="gray", ls=":", lw=1)
            ax.grid(alpha=0.3)
    for ax in axes[-1]:
        ax.set_xlabel("offered load")
    axes[0, 0].legend()
    fig.suptitle("Effect of receive antenna diversity on loss")
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def plot_edge(e: pd.DataFrame, load: float, antennas: int, out) -> None:
    e = e[(e.load == load) & (e.antennas == antennas)]
    pols = sorted(e.policy.unique())
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8), sharey=True)
    w = 0.38
    for j, c in enumerate(CLASSES):
        ax = axes[j]
        for off, z, color in ((-w / 2, "centre", "tab:green"), (w / 2, "edge", "tab:red")):
            g = e[(e["class"] == c) & (e.zone == z)].set_index("policy").reindex(pols)
            x = np.arange(len(pols)) + off
            ax.bar(x, g.loss, w, color=color, label=z,
                   yerr=[g.loss - g.lo, g.hi - g.loss], capsize=2)
        ax.set_xticks(range(len(pols)), pols)
        ax.set_title(c)
        ax.grid(alpha=0.3, axis="y")
    axes[0].set_ylabel("loss")
    axes[0].legend()
    fig.suptitle(f"Cell-centre (<{CENTRE_M:.0f} m) vs cell-edge (>{EDGE_M:.0f} m), "
                 f"load {load}, L={antennas}")
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--name", required=True)
    ap.add_argument("--edge-load", type=float, default=1.2)
    a = ap.parse_args()
    dc = pd.read_csv(RESULTS / f"{a.name}_class.csv")
    du = pd.read_csv(RESULTS / f"{a.name}_user.csv")

    s = summary(dc)
    s.to_csv(RESULTS / f"{a.name}_summary.csv", index=False)
    pairs = [("prio", "fifo"), ("dwrr", "fifo"), ("dwrr", "prio"), ("pf", "fifo"),
             ("fifobuf", "fifo"), ("prio", "fifobuf"), ("dwrr", "fifobuf"),
             ("sliced", "dwrr"), ("sliced", "fifo"), ("sliced", "prio")]
    paired(dc, pairs).to_csv(RESULTS / f"{a.name}_paired.csv", index=False)
    capacity(dc).to_csv(RESULTS / f"{a.name}_capacity.csv", index=False)
    e = edge_centre(du)
    e.to_csv(RESULTS / f"{a.name}_edge.csv", index=False)
    fairness(du).to_csv(RESULTS / f"{a.name}_fairness.csv", index=False)

    for k in sorted(dc.antennas.unique()):
        plot_policies(s, k, RESULTS / f"{a.name}_policies_L{k}.png")
    plot_diversity(s, RESULTS / f"{a.name}_diversity.png")
    load = min(sorted(e.load.unique()), key=lambda x: abs(x - a.edge_load))
    plot_edge(e, load, 1, RESULTS / f"{a.name}_edge_centre.png")
    print("wrote reports for", a.name)


if __name__ == "__main__":
    main()
