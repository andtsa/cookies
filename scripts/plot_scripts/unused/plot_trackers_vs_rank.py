"""
Tracker Prevalence vs. Website Rank

Correlates website popularity rank (embedded in crawl context) with tracker
cookie prevalence. All data loading goes through CookieDataset — no manual
JSON iteration or external rank-CSV join needed.

Views produced:
  1. Scatter plot: rank (log-scale x) vs. tracker share (y), one dot per site
  2. Binned bar chart: mean tracker share per rank tier (top 100, 101–1k, etc.)
  3. "At least one tracker" rate per rank tier

Usage:
    python scripts/plot_scripts/plot_trackers_vs_rank.py \\
        --data cookies_data --out plots/trackers
"""

import argparse
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    dataset,
    save_figure,
    BG,
    DARK,
    ACCENT,
    ACCENT2,
    COLORS,
)

# Canonical tier order — labels must match what CookieDataset._rank_tier produces.
RANK_TIER_ORDER = [
    "Top 10",
    "Top 50",
    "Top 100",
    "101–1k",
    "1k–10k",
    "10k–100k",
    "100k–1M",
]


def plot_trackers_vs_rank(data_dir: str, out_dir: str) -> None:
    apply_theme()

    print("Loading dataset…")
    ds = dataset(data_dir)
    sites = ds.sites

    # rank comes from crawl_context embedded in each site JSON by the crawler.
    matched = sites[sites["rank"].notna() & (sites["rank"] > 0)].copy()
    matched["rank"] = matched["rank"].astype(int)
    matched["has_tracker"] = matched["tracker_pct"] > 0

    print(f"  {len(sites):,} sites total, {len(matched):,} with rank info")
    if matched.empty:
        print(
            "No sites with rank info. Ensure the crawl embedded rank in crawl_context."
        )
        return

    # Pre-compute tier stats used by both bar charts in one pass.
    tier_stats = (
        matched[matched["rank_tier"].isin(RANK_TIER_ORDER)]
        .groupby("rank_tier", observed=True)
        .agg(
            mean_pct=("tracker_pct", "mean"),
            has_tracker_rate=("has_tracker", "mean"),
            n=("rank_tier", "size"),
        )
        .reindex(RANK_TIER_ORDER)
        .dropna()
    )
    x = np.arange(len(tier_stats))
    xlabels = tier_stats.index.tolist()

    fig, axes = plt.subplots(1, 3, figsize=(17, 6))

    # ── 1. Scatter ────────────────────────────────────────────────────────
    ax = axes[0]
    ax.scatter(
        matched["rank"],
        matched["tracker_pct"],
        alpha=0.45,
        s=18,
        color=ACCENT,
        edgecolors="none",
    )
    log_rank = np.log10(matched["rank"].clip(lower=1))
    z = np.polyfit(log_rank, matched["tracker_pct"], 1)
    x_line = np.linspace(log_rank.min(), log_rank.max(), 200)
    ax.plot(
        10**x_line,
        np.poly1d(z)(x_line),
        color=DARK,
        linewidth=1.5,
        linestyle="--",
        label="trend (log fit)",
    )
    ax.set_xscale("log")
    ax.set_xlabel("Website Rank (log scale)", fontsize=11)
    ax.set_ylabel("% Tracker Cookies", fontsize=11)
    ax.set_title("Tracker Share vs. Rank", fontsize=13, pad=10)
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)

    # ── 2. Mean tracker % per tier ────────────────────────────────────────
    ax2 = axes[1]
    bars = ax2.bar(
        x,
        tier_stats["mean_pct"],
        color=COLORS[: len(tier_stats)],
        edgecolor=BG,
        linewidth=0.8,
        alpha=0.9,
        width=0.6,
    )
    for bar, (_, row) in zip(bars, tier_stats.iterrows()):
        ax2.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.5,
            f"{row['mean_pct']:.1f}%\n(n={int(row['n'])})",
            ha="center",
            fontsize=9,
            color=DARK,
        )
    ax2.set_xticks(x)
    ax2.set_xticklabels(xlabels, rotation=15, ha="right")
    ax2.set_ylabel("Mean Tracker Share (%)", fontsize=11)
    ax2.set_title("Mean Tracker % by Rank Tier", fontsize=13, pad=10)
    ax2.grid(axis="y", alpha=0.35)
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.set_ylim(0, tier_stats["mean_pct"].max() * 1.3 if not tier_stats.empty else 1)

    # ── 3. "Has ≥1 tracker" rate per tier ────────────────────────────────
    ax3 = axes[2]
    has_tracker_pct = tier_stats["has_tracker_rate"] * 100
    bars3 = ax3.bar(
        x,
        has_tracker_pct,
        color=ACCENT2,
        edgecolor=BG,
        linewidth=0.8,
        alpha=0.9,
        width=0.6,
    )
    for bar, (_, row) in zip(bars3, tier_stats.iterrows()):
        ax3.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.5,
            f"{row['has_tracker_rate']*100:.0f}%\n(n={int(row['n'])})",
            ha="center",
            fontsize=9,
            color=DARK,
        )
    ax3.set_xticks(x)
    ax3.set_xticklabels(xlabels, rotation=15, ha="right")
    ax3.set_ylabel("Sites with ≥1 Tracker Cookie (%)", fontsize=11)
    ax3.set_title("Sites with ≥1 Tracker by Rank Tier", fontsize=13, pad=10)
    ax3.grid(axis="y", alpha=0.35)
    ax3.spines[["top", "right"]].set_visible(False)
    ax3.set_ylim(0, 115)

    fig.suptitle("Tracker Cookie Prevalence vs. Website Rank", fontsize=16, y=1.02)
    plt.tight_layout()
    save_figure(out_dir, "plot_trackers_vs_rank.png")
    print(
        f"\n{len(matched):,} sites plotted. Saved to {out_dir}/plot_trackers_vs_rank.png"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--out", default="./plots/trackers")
    args = parser.parse_args()
    plot_trackers_vs_rank(args.data, args.out)
