"""
Top Sites by Tracker Cookie Share
Horizontal bar ranking websites by the percentage of their cookies
flagged as trackers. Mirrors the longterm-offenders plot style.

Usage:
    python scripts/plot_scripts/plot_tracker_offenders.py --data cookies_data --out plots/trackers --top_n 25
"""

import argparse
import os
import sys

import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    load_tracker_cookies,
    save_figure,
    BG,
    DARK,
    LIGHT,
    ACCENT,
)


def plot_tracker_offenders(data_dir: str, out_dir: str, top_n: int = 25) -> None:
    apply_theme()
    df = load_tracker_cookies(data_dir)

    stats = (
        df.groupby("domain")
        .agg(total=("name", "count"), trackers=("is_tracker", "sum"))
        .reset_index()
    )
    # Filter tiny samples
    stats = stats[stats["total"] >= 2]
    stats["pct_tracker"] = stats["trackers"] / stats["total"] * 100

    top = stats.sort_values(["pct_tracker", "trackers"], ascending=[False, False]).head(
        top_n
    )

    # Gradient colours (same approach as plot_longterm_offenders)
    norm = plt.Normalize(top["pct_tracker"].min(), top["pct_tracker"].max())
    colors = [
        plt.matplotlib.colors.to_hex(
            plt.matplotlib.colors.hsv_to_rgb(
                [
                    0.06,
                    0.4 + 0.55 * norm(v),
                    0.9 - 0.35 * norm(v),
                ]
            )
        )
        for v in top["pct_tracker"]
    ]

    labels = top["domain"].str.replace(r"https?://", "", regex=True).str.rstrip("/")

    fig, ax = plt.subplots(figsize=(11, max(7, top_n * 0.42)))

    bars = ax.barh(
        labels,
        top["pct_tracker"],
        color=colors,
        edgecolor=BG,
        linewidth=0.6,
        height=0.72,
    )

    ax.invert_yaxis()
    ax.tick_params(axis="both", labelsize=12)

    for bar, pct, count in zip(bars, top["pct_tracker"], top["trackers"]):
        ax.text(
            bar.get_width() + 0.8,
            bar.get_y() + bar.get_height() / 2,
            f"{pct:.0f}%  ({count:.0f} trackers)",
            va="center",
            fontsize=12,
            color=DARK,
        )

    ax.set_xlim(0, 115)
    ax.axvline(100, color=LIGHT, linewidth=0.8, linestyle=":")

    ax.set_xlabel("% of Cookies Flagged as Trackers", fontsize=14)
    ax.set_title(f"Top {top_n} Websites by Tracker Cookie Share", fontsize=16, pad=15)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", alpha=0.3)

    plt.tight_layout()
    save_figure(out_dir, "plot_tracker_offenders.png", "plot_tracker_offenders.pdf")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--out", default="./plots/trackers")
    parser.add_argument("--top_n", default=25, type=int)
    args = parser.parse_args()
    plot_tracker_offenders(args.data, args.out, args.top_n)
