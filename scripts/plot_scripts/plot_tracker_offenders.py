"""
Top Sites by Tracker Cookie Share
Horizontal bar ranking websites by the percentage of their cookies flagged as trackers.

Usage:
    python scripts/plot_scripts/plot_tracker_offenders.py --data cookies_data --out plots/trackers --top_n 25
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
    gradient_colors,
    hbar_chart,
    annotate_hbars,
    clean_ax,
    LIGHT,
)


def plot_tracker_offenders(data_dir: str, out_dir: str, top_n: int = 25) -> None:
    apply_theme()
    df = load_tracker_cookies(data_dir)
    stats = (
        df.groupby("domain")
        .agg(total=("name", "count"), trackers=("is_tracker", "sum"))
        .reset_index()
    )
    stats = stats[stats["total"] >= 2]
    stats["pct_tracker"] = stats["trackers"] / stats["total"] * 100
    top = stats.sort_values(["pct_tracker", "trackers"], ascending=False).head(top_n)

    labels = top["domain"].str.replace(r"https?://", "", regex=True).str.rstrip("/")
    fig, ax = plt.subplots(figsize=(11, max(7, top_n * 0.42)))
    bars = hbar_chart(
        ax, labels, top["pct_tracker"], colors=gradient_colors(top["pct_tracker"])
    )
    annotate_hbars(
        ax,
        bars,
        [
            f"{p:.0f}%  ({c:.0f} trackers)"
            for p, c in zip(top["pct_tracker"], top["trackers"])
        ],
        offset=0.8,
        fontsize=12,
    )
    ax.set_xlim(0, 115)
    ax.axvline(100, color=LIGHT, linewidth=0.8, linestyle=":")
    ax.set_xlabel("% of Cookies Flagged as Trackers", fontsize=14)
    ax.set_title(f"Top {top_n} Websites by Tracker Cookie Share", fontsize=16, pad=15)
    clean_ax(ax)
    ax.tick_params(axis="both", labelsize=12)
    save_figure(out_dir, "plot_tracker_offenders.png", "plot_tracker_offenders.pdf")


if __name__ == "__main__":
    p = make_parser(out="./plots/trackers")
    p.add_argument("--top_n", default=25, type=int)
    args = p.parse_args()
    plot_tracker_offenders(args.data, args.out, args.top_n)
