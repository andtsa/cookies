"""
Cookie Lifetime Bucket Distribution
A horizontal bar showing how all cookies fall into lifetime buckets.

Usage:
    python scripts/plot_scripts/plot_lifetime_buckets.py --data cookies_data --out plots/cookie_lifetime
"""

import os
import sys

import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    load_cookie_data,
    save_figure,
    make_parser,
    hbar_chart,
    annotate_hbars,
    clean_ax,
    BUCKETS,
    BUCKET_COLORS,
    MID,
)


def plot_buckets(data_dir: str, out_dir: str) -> None:
    apply_theme()
    _, cookies_df = load_cookie_data(data_dir)
    counts = cookies_df["bucket"].value_counts().reindex(BUCKETS, fill_value=0)
    total = counts.sum()
    pcts = counts / total * 100

    fig, ax = plt.subplots(figsize=(9, 5))
    bars = hbar_chart(ax, BUCKETS, pcts, colors=BUCKET_COLORS, height=0.65)
    annotate_hbars(
        ax,
        bars,
        [f"{p:.1f}% ({c:,})" for p, c in zip(pcts, counts)],
        offset=0.4,
        fontsize=9,
    )
    ax.set_xlim(0, pcts.max() * 1.28)
    ax.set_xlabel("Share of All Cookies (%)")
    ax.set_title("Cookie Lifetime Distribution")
    clean_ax(ax, alpha=0.35)
    ax.text(
        0.99,
        0.03,
        f"Total cookies: {total:,}",
        transform=ax.transAxes,
        ha="right",
        fontsize=8.5,
        color=MID,
    )
    save_figure(out_dir, "plot_lifetime_buckets.png")


if __name__ == "__main__":
    args = make_parser(out="./plots/cookie_lifetime").parse_args()
    plot_buckets(args.data, args.out)
