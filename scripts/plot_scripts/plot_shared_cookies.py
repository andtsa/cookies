"""
Cross-Site Shared Identifiers
Two panels:
  (A) Top identifiers by number of distinct sites they appear on, colored by
      whether they are a known tracker, annotated with the third-party split.
  (B) How many cross-site groups each match mode finds (name-md5 vs
      value-entropy vs name-cluster) — shows the added reach of the fuzzy/entropy
      modes over exact name+value matching.

Reuses the analysis helpers from scripts/find_shared_cookies.py so the grouping
logic is never duplicated. Reads PROCESSED data (run process_cookies.py first).

Usage:
    python scripts/plot_scripts/plot_shared_cookies.py --data cookies_data_processed --out plots/shared --top_n 20
"""

import argparse
import os
import sys

import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    dataset,
    save_figure,
    BG,
    DARK,
    LIGHT,
    ACCENT,
    ACCENT2,
    MID,
)

_MATCH_MODES = ["name-md5", "value-entropy", "name-cluster"]
_MODE_COLORS = {"name-md5": MID, "value-entropy": ACCENT2, "name-cluster": ACCENT}


def plot_shared_cookies(
    data_dir: str, out_dir: str, top_n: int = 20, min_sites: int = 2
) -> None:
    apply_theme()
    ds = dataset(data_dir)

    # Panel A uses name-cluster (the most inclusive) so families show their real
    # cross-site spread; Panel B compares all three modes. The dataset computes
    # the grouping (no processed-data prerequisite, no duplicated logic).
    results_by_mode = {
        mode: ds.shared(match_mode=mode, min_sites=min_sites) for mode in _MATCH_MODES
    }
    print(results_by_mode)
    panel_a = results_by_mode["name-cluster"][:top_n]

    fig, (axA, axB) = plt.subplots(
        1, 2, figsize=(16, max(7, top_n * 0.42)), gridspec_kw={"width_ratios": [2.1, 1]}
    )

    # ---- Panel A: top shared identifiers ----
    if panel_a:
        labels = [r["label"] for r in panel_a][::-1]
        counts = [r["site_count"] for r in panel_a][::-1]
        is_tracker = [r["any_tracker"] for r in panel_a][::-1]
        tp = [r["distinct_first_parties"] for r in panel_a][::-1]
        colors = [ACCENT if t else MID for t in is_tracker]

        bars = axA.barh(
            labels, counts, color=colors, edgecolor=BG, linewidth=0.6, height=0.72
        )
        for bar, c, n1p in zip(bars, counts, tp):
            axA.text(
                bar.get_width() + max(counts) * 0.01,
                bar.get_y() + bar.get_height() / 2,
                f"{c} sites  ({n1p} distinct 1p)",
                va="center",
                fontsize=10,
                color=DARK,
            )
        axA.set_xlim(0, max(counts) * 1.25)
    else:
        axA.text(
            0.5,
            0.5,
            "No cross-site identifiers found",
            ha="center",
            va="center",
            transform=axA.transAxes,
            color=DARK,
        )

    axA.set_xlabel("Distinct sites the identifier appears on", fontsize=13)
    axA.set_title(
        f"Top {top_n} cross-site identifiers (name-cluster)", fontsize=15, pad=12
    )
    axA.spines[["top", "right"]].set_visible(False)
    axA.grid(axis="x", alpha=0.3)

    # Legend for tracker coloring
    from matplotlib.patches import Patch

    axA.legend(
        handles=[
            Patch(facecolor=ACCENT, label="Known tracker"),
            Patch(facecolor=MID, label="Not flagged"),
        ],
        loc="lower right",
        fontsize=11,
    )

    # ---- Panel B: match-mode comparison ----
    mode_counts = [len(results_by_mode[m]) for m in _MATCH_MODES]
    mode_colors = [_MODE_COLORS[m] for m in _MATCH_MODES]
    bbars = axB.bar(
        _MATCH_MODES,
        mode_counts,
        color=mode_colors,
        edgecolor=BG,
        linewidth=0.8,
        width=0.62,
    )
    for bar, c in zip(bbars, mode_counts):
        axB.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(mode_counts + [1]) * 0.02,
            str(c),
            ha="center",
            va="bottom",
            fontsize=12,
            color=DARK,
            fontweight="bold",
        )
    axB.set_ylabel(f"# groups shared across ≥{min_sites} sites", fontsize=12)
    axB.set_title("Identifiers found per match mode", fontsize=15, pad=12)
    axB.set_ylim(0, max(mode_counts + [1]) * 1.18)
    axB.tick_params(axis="x", labelrotation=20)
    axB.spines[["top", "right"]].set_visible(False)
    axB.grid(axis="y", alpha=0.3)

    fig.suptitle("Cross-Site ID Persistence", fontsize=18, fontweight="bold", y=1.02)
    plt.tight_layout()
    save_figure(out_dir, "plot_shared_cookies.png", "plot_shared_cookies.pdf")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--out", default="./plots/shared")
    parser.add_argument("--top_n", default=20, type=int)
    parser.add_argument("--min_sites", default=2, type=int)
    args = parser.parse_args()
    plot_shared_cookies(args.data, args.out, args.top_n, args.min_sites)
