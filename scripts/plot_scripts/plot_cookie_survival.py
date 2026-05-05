"""
Survival Curve of Cookie Lifetimes
Shows what % of persistent cookies are still active after X days.

Usage:
    python scripts/plot_scripts/plot_cookie_survival.py --data cookies_data --out plots/cookie_lifetime
"""

import argparse
import numpy as np
import matplotlib.pyplot as plt
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from utils import apply_theme, load_cookie_data, BG, ACCENT, ACCENT2, DARK, MID, LIGHT


def plot_survival(data_dir: str, out_dir: str):
    apply_theme()
    _, cookies_df = load_cookie_data(data_dir)

    # Keep only persistent cookies
    persistent = cookies_df[cookies_df["cookie_type"] == "persistent"].copy()

    lifetimes = np.sort(
        persistent["lifetime_days"].dropna().values
    )

    # Compute survival function
    cdf = np.arange(1, len(lifetimes) + 1) / len(lifetimes)
    survival = (1 - cdf) * 100

    fig, ax = plt.subplots(figsize=(9, 5))

    # Main survival line
    ax.plot(
        lifetimes,
        survival,
        color=ACCENT,
        linewidth=2.5,
        zorder=3
    )

    ax.fill_between(
        lifetimes,
        survival,
        alpha=0.12,
        color=ACCENT
    )

    # Milestones
    milestones = [
        (1, "1 day"),
        (7, "1 week"),
        (30, "1 month"),
        (180, "6 months"),
        (365, "1 year"),
    ]



    for days, label in milestones:
        idx = np.searchsorted(lifetimes, days, "right")
        pct_alive = (1 - idx / len(lifetimes)) * 100

        # Vertical reference line
        ax.axvline(
            days,
            color=LIGHT,
            linewidth=1,
            linestyle="--",
            zorder=1
        )

        # Marker point
        ax.scatter(
            [days],
            [pct_alive],
            color=ACCENT2,
            s=28,
            zorder=4
        )
        ax.annotate(
            f"{pct_alive:.0f}%",
            xy=(days, pct_alive),
            xytext=(6, 4),
            textcoords="offset points",
            fontsize=10,
            color=DARK,
            ha="left",
            va="bottom"
        )



    # Axis styling
    ax.set_xscale("symlog", linthresh=1)
    ax.set_xticks([0, 1, 7, 30, 90, 180, 365, 730])
    ax.set_xticklabels(
        ["0", "1d", "7d", "1m", "3m", "6m", "1y", "2y"]
    )

    ax.set_xlim(left=0)
    ax.set_ylim(0, 108)

    ax.set_xlabel("Cookie Lifetime (log scale)")
    ax.set_ylabel("% of Cookies Still Active")
    ax.set_title("Lifetime of Persistent Cookies")

    ax.grid(axis="y", alpha=0.4)



    # Sample size text
    n_cookies = len(lifetimes)
    ax.text(
        0.01,
        0.01,
        f"n = {n_cookies:,} persistent cookies",
        transform=ax.transAxes,
        ha="left",
        fontsize=10,
        color=MID,
        va= "bottom"
    )

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "plot_cookie_survival.png")

    plt.savefig(
        out_path,
        dpi=300,
        bbox_inches="tight",
        facecolor=BG
    )

    plt.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data",
        default="./cookie_data",
        help="Path to cookie_data folder"
    )
    parser.add_argument(
        "--out",
        default="./plots",
        help="Output folder for plots"
    )

    args = parser.parse_args()
    plot_survival(args.data, args.out)
