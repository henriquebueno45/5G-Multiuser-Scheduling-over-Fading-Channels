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

POLICIES = ["fifo", "fifobuf", "prio", "dwrr", "pf", "sliced"]
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
            if i % 50 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)}", flush=True)


def plot_csi_fig(sel: pd.DataFrame, lang: str = "pt", out_path: Path | str = None) -> None:
    fig, axes = plt.subplots(len(CLASSES), len(SPEEDS), figsize=(11, 7.2), sharex=True, sharey="row")
    colors = {
        "fifo": "tab:red",
        "fifobuf": "tab:orange",
        "prio": "tab:blue",
        "dwrr": "tab:green",
        "pf": "tab:purple",
        "sliced": "tab:cyan",
    }
    if lang == "pt":
        labels_map = {
            "fifo": "FIFO", "fifobuf": "FIFO Tail-Drop", "prio": "Prioridade",
            "dwrr": "DWRR", "pf": "PF", "sliced": "Hierárquico",
        }
        class_labels = {
            "voice": "URLLC",
            "video": "eMBB GBR",
            "data": "eMBB non-GBR",
        }
        speed_fmt = lambda v: f"Velocidade: {str(v).replace('.', ',')} m/s"
        ylabel_fmt = lambda c: f"Perda {class_labels[c]} (%)"
        xlabel = "Qualidade da CSI (atraso CQI / margem de back-off)"
        csi_ticks = ["Perfeito", "5 ms / 0 dB", "5 ms / 3 dB", "5 ms / 6 dB", "10 ms / 6 dB"]
    else:
        labels_map = {
            "fifo": "FIFO", "fifobuf": "FIFO Tail-Drop", "prio": "Priority",
            "dwrr": "DWRR", "pf": "PF", "sliced": "Hierarchical",
        }
        class_labels = {
            "voice": "URLLC",
            "video": "eMBB GBR",
            "data": "eMBB non-GBR",
        }
        speed_fmt = lambda v: f"Speed: {v:g} m/s"
        ylabel_fmt = lambda c: f"{class_labels[c]} Loss (%)"
        xlabel = "Channel State Information (CQI delay / back-off margin)"
        csi_ticks = ["Perfect", "5 ms / 0 dB", "5 ms / 3 dB", "5 ms / 6 dB", "10 ms / 6 dB"]

    w = 0.13
    handles = []
    labels = []
    for j, v in enumerate(SPEEDS):
        for i, c in enumerate(CLASSES):
            ax = axes[i, j]
            for q, p in enumerate(POLICIES):
                g = sel[(sel.speed == v) & (sel.policy == p) & (sel["class"] == c)]
                g = g.set_index("csi").reindex(list(CSI))
                loss_pct = g.loss * 100
                yerr = [(g.loss - g.loss_lo) * 100, (g.loss_hi - g.loss) * 100]
                bar = ax.bar(np.arange(len(CSI)) + (q - 2.5) * w, loss_pct, w,
                             color=colors[p], label=labels_map[p],
                             yerr=yerr, capsize=1.5)
                if i == 0 and j == 0:
                    handles.append(bar)
                    labels.append(labels_map[p])
            if i == 0:
                ax.set_title(speed_fmt(v), fontsize=11, fontweight="bold", pad=8)
            if j == 0:
                ax.set_ylabel(ylabel_fmt(c), fontsize=10, fontweight="bold")
            ax.grid(alpha=0.3, axis="y")
            ax.set_ylim(-2, 105)
            ax.set_yticks([0, 20, 40, 60, 80, 100])
    for ax in axes[-1]:
        ax.set_xticks(range(len(CSI)), csi_ticks, fontsize=9)
        ax.set_xlabel(xlabel, fontsize=9.5, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.88])
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.98),
               ncol=6, fontsize=9.5, frameon=True, edgecolor="#ccc", facecolor="white")
    if out_path:
        fig.savefig(out_path, dpi=140)
    plt.close(fig)


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

    # PT-BR plot for academic report
    plot_csi_fig(sel, lang="pt", out_path="report/figures/csi_loss.png")
    # EN plot for repository results / README
    plot_csi_fig(sel, lang="en", out_path=RESULTS / "csi_loss.png")

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
