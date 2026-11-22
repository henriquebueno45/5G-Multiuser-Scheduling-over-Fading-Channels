"""Compact figure for the article: loss versus offered load, one panel per class (1 antenna)."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from analysis.experiments import RESULTS  # noqa: E402

COLORS = {"fifo": "tab:red", "fifobuf": "tab:orange", "prio": "tab:blue",
          "dwrr": "tab:green", "pf": "tab:purple", "sliced": "tab:cyan"}
TITLES = {"voice": "Voz", "video": "Vídeo", "data": "Dados"}


def main() -> None:
    s = pd.read_csv(RESULTS / "main_summary.csv")
    s = s[s.antennas == 1]
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.2), sharey=True)
    for ax, c in zip(axes, TITLES):
        for p, col in COLORS.items():
            g = s[(s.policy == p) & (s["class"] == c)].sort_values("load")
            ax.plot(g.load, g.loss * 100, color=col, label=p, marker="o", ms=3)
            ax.fill_between(g.load, g.loss_lo * 100, g.loss_hi * 100, color=col, alpha=0.15)
        ax.set_title(TITLES[c])
        ax.set_xlabel("carga oferecida (1 = saturação)")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("perda (%)")
    axes[0].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig("report/figures/art_loss.png", dpi=150)


if __name__ == "__main__":
    main()
