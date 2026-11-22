"""Compact figure for the article: loss versus offered load, one panel per class (1 antenna)."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from analysis.experiments import RESULTS  # noqa: E402

COLORS = {
    "fifo": "tab:red",
    "fifobuf": "tab:orange",
    "prio": "tab:blue",
    "dwrr": "tab:green",
    "pf": "tab:purple",
    "sliced": "tab:cyan",
}
LABELS_PT = {
    "fifo": "FIFO",
    "fifobuf": "FIFO Tail-Drop",
    "prio": "Prioridade",
    "dwrr": "DWRR",
    "pf": "PF",
    "sliced": "Hierárquico",
}
LABELS_EN = {
    "fifo": "FIFO",
    "fifobuf": "FIFO Tail-Drop",
    "prio": "Priority",
    "dwrr": "DWRR",
    "pf": "PF",
    "sliced": "Hierarchical",
}
TITLES = {
    "voice": "URLLC",
    "video": "eMBB GBR",
    "data": "eMBB non-GBR",
}


def make_fig(s: pd.DataFrame, lang: str = "pt", out_path: str = "report/figures/art_loss.png") -> None:
    labels_map = LABELS_PT if lang == "pt" else LABELS_EN
    xlabel = "Carga oferecida (1 = saturação)" if lang == "pt" else "Offered load (1 = saturation)"
    ylabel = "Perda de pacotes (%)" if lang == "pt" else "Packet loss (%)"

    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.4), sharey=True)
    handles = []
    labels = []
    for ax, c in zip(axes, TITLES):
        for p, col in COLORS.items():
            g = s[(s.policy == p) & (s["class"] == c)].sort_values("load")
            line = ax.plot(g.load, g.loss * 100, color=col, label=labels_map[p], marker="o", ms=3)[0]
            ax.fill_between(g.load, g.loss_lo * 100, g.loss_hi * 100, color=col, alpha=0.15)
            if len(handles) < len(COLORS):
                handles.append(line)
                labels.append(labels_map[p])
        ax.set_title(TITLES[c], fontweight="bold", fontsize=11)
        ax.set_xlabel(xlabel, fontsize=9.5)
        ax.grid(alpha=0.3)
        ax.set_ylim(-2, 103)
    axes[0].set_ylabel(ylabel, fontsize=9.5)
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.99),
               ncol=6, fontsize=9, frameon=True, edgecolor="#ccc")
    fig.tight_layout(rect=[0, 0, 1, 0.90])
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"saved {out_path}")


def main() -> None:
    s = pd.read_csv(RESULTS / "main_summary.csv")
    s = s[s.antennas == 1]
    make_fig(s, lang="pt", out_path="report/figures/art_loss.png")
    make_fig(s, lang="en", out_path=str(RESULTS / "art_loss.png"))


if __name__ == "__main__":
    main()
