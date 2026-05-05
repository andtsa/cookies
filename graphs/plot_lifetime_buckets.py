"""
Cookie Lifetime Bucket Distribution
A stacked bar showing how all cookies across all 500 sites fall into
lifetime buckets. Instantly answers "what proportion of cookies are
long-lived?"

Usage:
    python graphs/plot_lifetime_buckets.py --data cookies_data --out plots/cookie_lifetime
"""

import argparse
import matplotlib.pyplot as plt
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    load_cookie_data,
    BUCKETS,
    BUCKET_COLORS,
    lifetime_bucket,
    BG,
    DARK,
    MID
)


def plot_buckets(data_dir: str, out_dir: str):
    apply_theme()
    _, cookies_df = load_cookie_data(data_dir)

    cookies_df["bucket"] = cookies_df.apply(
        lambda r: lifetime_bucket(r["lifetime_days"], r["session"]),
        axis=1
    )

    counts = cookies_df["bucket"].value_counts().reindex(
        BUCKETS,
        fill_value=0
    )

    total = counts.sum()
    pcts = counts / total * 100

    fig, ax = plt.subplots(figsize=(9, 5))

    bars = ax.barh(
        BUCKETS,
        pcts,
        color=BUCKET_COLORS,
        edgecolor=BG,
        linewidth=0.8,
        height=0.65
    )

    for bar, pct, count in zip(bars, pcts, counts):
        ax.text(
            bar.get_width() + 0.4,
            bar.get_y() + bar.get_height() / 2,
            f"{pct:.1f}% ({count:,})",
            va="center",
            fontsize=9,
            color=DARK
        )

    ax.set_xlim(0, pcts.max() * 1.28)
    ax.set_xlabel("Share of All Cookies (%)")
    ax.set_title("Cookie Lifetime Distribution")
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.35)

    ax.spines[["top", "right"]].set_visible(False)

    ax.text(
        0.99,
        0.03,
        f"Total cookies: {total:,}",
        transform=ax.transAxes,
        ha="right",
        fontsize=8.5,
        color=MID
    )

    plt.tight_layout()

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "plot_lifetime_buckets.png")

    plt.savefig(
        out_path,
        dpi=300,
        bbox_inches="tight",
        facecolor=BG
    )

    print(f"Saved → {out_path}")
    plt.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookie_data")
    parser.add_argument("--out", default="./plots")
    args = parser.parse_args()

    plot_buckets(args.data, args.out)
