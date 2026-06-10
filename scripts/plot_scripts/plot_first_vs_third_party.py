"""
Plot — First-party vs Third-party: All Cookies vs Trackers

Usage:
    python scripts/plot_scripts/plot_first_vs_third_party.py \
        --data ../../cookies_data \
        --out plots
"""

import argparse
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

from utils import (
    apply_theme,
    dataset,
    save_figure,
    COLORS,
    BG,
)


def plot_first_vs_third_party(data_dir: str, out_dir: str):
    apply_theme()

    ds = dataset(data_dir)

    # ── All cookies ──
    cookies = ds.cookies
    total_cookies = len(cookies)
    third_cookies = cookies["set_by_third_party"].sum()
    first_cookies = total_cookies - third_cookies

    # ── Trackers only ──
    classified = ds.classified_cookies
    trackers = classified[classified["tracker_like"] == True]
    total_trackers = len(trackers)
    third_trackers = trackers["set_by_third_party"].sum()
    first_trackers = total_trackers - third_trackers

    # ── Percentages ──
    first_pct = [
        first_cookies / total_cookies * 100,
        first_trackers / total_trackers * 100,
    ]
    third_pct = [
        third_cookies / total_cookies * 100,
        third_trackers / total_trackers * 100,
    ]

    labels = [
        f"All cookies\n(n={total_cookies:,})",
        f"Trackers only\n(n={total_trackers:,})",
    ]

    first_color = COLORS[0]
    third_color = COLORS[2]

    fig, ax = plt.subplots(figsize=(8, 4))

    y = np.arange(len(labels))
    bar_h = 0.5

    bars_first = ax.barh(
        y, first_pct, height=bar_h, color=first_color, label="First-party"
    )
    bars_third = ax.barh(
        y,
        third_pct,
        height=bar_h,
        left=first_pct,
        color=third_color,
        label="Third-party",
    )

    # ── % labels inside bars ──
    for i, (fp, tp) in enumerate(zip(first_pct, third_pct)):
        if fp >= 5:
            ax.text(
                fp / 2,
                i,
                f"{fp:.1f}%",
                ha="center",
                va="center",
                fontsize=10,
                fontweight="bold",
                color="white",
            )
        if tp >= 5:
            ax.text(
                fp + tp / 2,
                i,
                f"{tp:.1f}%",
                ha="center",
                va="center",
                fontsize=10,
                fontweight="bold",
                color="white",
            )

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=11)
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.tick_params(axis="x", labelsize=10)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)

    ax.legend(
        handles=[bars_first, bars_third],
        labels=["First-party", "Third-party"],
        loc="lower right",
        fontsize=10,
        frameon=False,
    )

    ax.set_title(
        "First-party vs Third-party: All Cookies and Trackers",
        pad=10,
        fontsize=13,
    )

    plt.tight_layout()
    save_figure(out_dir, "first_vs_third_party.png", "first_vs_third_party.pdf")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="../../cookies_data")
    parser.add_argument("--out", default="plots")
    args = parser.parse_args()
    plot_first_vs_third_party(args.data, args.out)
