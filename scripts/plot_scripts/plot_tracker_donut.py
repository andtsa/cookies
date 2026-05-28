"""
Tracker vs Non-Tracker Cookie Distribution
A donut showing the overall share of tracker vs non-tracker cookies
(requires cookies collected with --tracker-lists enabled).

Usage:
    python scripts/plot_scripts/plot_tracker_donut.py --data cookies_data --out plots/trackers
"""

import argparse
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    load_tracker_cookies,
    save_figure,
    BG,
    DARK,
    ACCENT,
    BUCKET_COLORS,
)


def plot_tracker_donut(data_dir: str, out_dir: str) -> None:
    apply_theme()
    df = load_tracker_cookies(data_dir)

    total = len(df)
    n_tracker = df["is_tracker"].sum()
    n_clean = total - n_tracker
    pct_t = n_tracker / total * 100
    pct_c = n_clean / total * 100

    values = [pct_t, pct_c]
    labels = ["Tracker", "Non-Tracker"]
    colors = [ACCENT, BUCKET_COLORS[1]]  # warm orange vs soft grey

    fig, ax = plt.subplots(figsize=(7, 7))

    wedges = ax.pie(
        values,
        colors=colors,
        startangle=90,
        wedgeprops={"width": 0.5, "edgecolor": BG, "linewidth": 2},
    )[0]

    # Centre annotation
    ax.text(
        0,
        0,
        f"{pct_t:.1f}%\ntrackers",
        ha="center",
        va="center",
        fontsize=16,
        fontweight="bold",
        color=ACCENT,
    )

    # Outside labels with leader lines
    for i, wedge in enumerate(wedges):
        angle = (wedge.theta2 + wedge.theta1) / 2
        x_tip = 0.98 * np.cos(np.deg2rad(angle))
        y_tip = 0.98 * np.sin(np.deg2rad(angle))
        x_lbl = 1.28 * np.cos(np.deg2rad(angle))
        y_lbl = 1.28 * np.sin(np.deg2rad(angle))

        count = n_tracker if i == 0 else n_clean
        ax.annotate(
            f"{labels[i]}\n{values[i]:.1f}%  ({count:,})",
            xy=(x_tip, y_tip),
            xytext=(x_lbl, y_lbl),
            ha="center",
            va="center",
            fontsize=11,
            fontweight="bold",
            color=DARK,
            arrowprops=dict(arrowstyle="-", color=DARK, lw=1.2),
        )

    ax.set_title("Tracker vs Non-Tracker Cookies", pad=15)

    save_figure(out_dir, "plot_tracker_donut.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--out", default="./plots/trackers")
    args = parser.parse_args()
    plot_tracker_donut(args.data, args.out)
