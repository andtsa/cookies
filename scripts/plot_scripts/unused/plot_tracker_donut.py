"""
Tracker vs Non-Tracker Cookie Distribution
A donut showing the overall share of tracker vs non-tracker cookies.

Usage:
    python scripts/plot_scripts/plot_tracker_donut.py --data cookies_data --out plots/trackers
"""

import os
import sys

import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    load_tracker_cookies,
    save_figure,
    make_parser,
    donut_chart,
    ACCENT,
    BUCKET_COLORS,
)


def plot_tracker_donut(data_dir: str, out_dir: str) -> None:
    apply_theme()
    df = load_tracker_cookies(data_dir)
    total = len(df)
    n_tracker = int(df["is_tracker"].sum())
    n_clean = total - n_tracker

    fig, ax = plt.subplots(figsize=(7, 7))
    donut_chart(
        ax,
        ["Tracker", "Non-Tracker"],
        [n_tracker / total * 100, n_clean / total * 100],
        [ACCENT, BUCKET_COLORS[1]],
        center_text=f"{n_tracker / total * 100:.1f}%\ntrackers",
        counts=[n_tracker, n_clean],
    )
    ax.set_title("Tracker vs Non-Tracker Cookies", pad=15)
    save_figure(out_dir, "plot_tracker_donut.png")


if __name__ == "__main__":
    args = make_parser(out="./plots/trackers").parse_args()
    plot_tracker_donut(args.data, args.out)
