"""
Tracker Prevalence vs. Website Rank

Joins the crawled sites against list_websites_1M.csv (rank,domain — no header)
to correlate website popularity rank with tracker cookie prevalence.

Views produced:
  1. Scatter plot: rank (log-scale x) vs. tracker share (y), one dot per site
  2. Binned bar chart: mean tracker share per rank tier (top 100, 101–1k, etc.)
  3. "At least one tracker" rate per rank tier

Usage:
    python scripts/plot_scripts/plot_trackers_vs_rank.py \\
        --data cookies_data --rank list_websites_1M.csv --out plots/trackers
"""

import argparse
import csv
import os
import sys
from collections import defaultdict

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import tldextract

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    _iter_cookie_files,
    save_figure,
    BG,
    DARK,
    MID,
    LIGHT,
    ACCENT,
    ACCENT2,
    COLORS,
)

RANK_TIERS = [
    (1, 100, "Top 100"),
    (101, 1_000, "101–1k"),
    (1_001, 10_000, "1k–10k"),
    (10_001, 100_000, "10k–100k"),
    (100_001, 1_000_000, "100k–1M"),
]


def load_rank_csv(rank_csv: str) -> dict[str, int]:
    """Return {registered_domain -> rank} from the headerless rank CSV."""
    ranks: dict[str, int] = {}
    with open(rank_csv, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 2:
                continue
            try:
                rank = int(row[0])
            except ValueError:
                continue
            domain = row[1].strip().lower().lstrip("www.")
            registered = tldextract.extract(domain).registered_domain or domain
            if registered:
                ranks[registered] = rank
    return ranks


def _to_bool_tracker(val) -> bool:
    if val is None or val is False:
        return False
    return bool(val) if isinstance(val, bool) else bool((val or {}).get("lists"))


def load_site_tracker_data(data_dir: str) -> pd.DataFrame:
    """One row per site: registered_domain, pct_trackers, has_tracker, total_cookies."""
    rows = []
    for domain, browser, data in _iter_cookie_files(data_dir):
        target_url = data.get("target_url", "")
        registered = tldextract.extract(target_url).registered_domain or domain

        cookies = data.get("cookies", [])
        if not cookies:
            continue

        has_tracker_col = any("is_tracker" in c for c in cookies)
        if not has_tracker_col:
            continue

        n_total = len(cookies)
        n_tracker = sum(_to_bool_tracker(c.get("is_tracker")) for c in cookies)
        rows.append(
            {
                "registered_domain": registered,
                "total_cookies": n_total,
                "n_tracker": n_tracker,
                "pct_trackers": n_tracker / n_total * 100 if n_total else 0.0,
                "has_tracker": n_tracker > 0,
            }
        )
    return pd.DataFrame(rows).drop_duplicates(subset="registered_domain")


def plot_trackers_vs_rank(data_dir: str, rank_csv: str, out_dir: str) -> None:
    apply_theme()

    print("Loading rank data…")
    ranks = load_rank_csv(rank_csv)
    print(f"  {len(ranks):,} domains in rank CSV")

    print("Loading site cookie data…")
    df = load_site_tracker_data(data_dir)
    print(f"  {len(df):,} sites with tracker annotation")

    if df.empty:
        print("No is_tracker data found. Re-collect with --tracker-lists.")
        return

    df["rank"] = df["registered_domain"].map(ranks)
    matched = df.dropna(subset=["rank"]).copy()
    matched["rank"] = matched["rank"].astype(int)

    n_matched = len(matched)
    n_unmatched = len(df) - n_matched
    print(f"  Matched {n_matched:,} sites to ranks ({n_unmatched:,} unmatched)")

    if matched.empty:
        print(
            "No sites matched to ranks. Ensure --rank points at list_websites_1M.csv "
            "and the sites were crawled from that list."
        )
        return

    fig, axes = plt.subplots(1, 3, figsize=(17, 6))

    # ── 1. Scatter ────────────────────────────────────────────────────────
    ax = axes[0]
    ax.scatter(
        matched["rank"],
        matched["pct_trackers"],
        alpha=0.45,
        s=18,
        color=ACCENT,
        edgecolors="none",
    )
    # Trend line in log-rank space
    log_rank = np.log10(matched["rank"])
    z = np.polyfit(log_rank, matched["pct_trackers"], 1)
    p = np.poly1d(z)
    x_line = np.linspace(log_rank.min(), log_rank.max(), 200)
    ax.plot(
        10**x_line,
        p(x_line),
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
    tier_labels, tier_means, tier_ns = [], [], []
    for lo, hi, label in RANK_TIERS:
        sub = matched[(matched["rank"] >= lo) & (matched["rank"] <= hi)]
        if len(sub) > 0:
            tier_labels.append(label)
            tier_means.append(sub["pct_trackers"].mean())
            tier_ns.append(len(sub))

    x = np.arange(len(tier_labels))
    bars = ax2.bar(
        x,
        tier_means,
        color=COLORS[: len(tier_labels)],
        edgecolor=BG,
        linewidth=0.8,
        alpha=0.9,
        width=0.6,
    )
    for bar, mean, n in zip(bars, tier_means, tier_ns):
        ax2.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.5,
            f"{mean:.1f}%\n(n={n})",
            ha="center",
            fontsize=9,
            color=DARK,
        )
    ax2.set_xticks(x)
    ax2.set_xticklabels(tier_labels, rotation=15, ha="right")
    ax2.set_ylabel("Mean Tracker Share (%)", fontsize=11)
    ax2.set_title("Mean Tracker % by Rank Tier", fontsize=13, pad=10)
    ax2.grid(axis="y", alpha=0.35)
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.set_ylim(0, max(tier_means) * 1.3 if tier_means else 1)

    # ── 3. "Has ≥1 tracker" rate per tier ────────────────────────────────
    ax3 = axes[2]
    tier_has_tracker = []
    for lo, hi, label in RANK_TIERS:
        sub = matched[(matched["rank"] >= lo) & (matched["rank"] <= hi)]
        if len(sub) > 0:
            tier_has_tracker.append(sub["has_tracker"].mean() * 100)

    bars3 = ax3.bar(
        x,
        tier_has_tracker,
        color=ACCENT2,
        edgecolor=BG,
        linewidth=0.8,
        alpha=0.9,
        width=0.6,
    )
    for bar, pct, n in zip(bars3, tier_has_tracker, tier_ns):
        ax3.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.5,
            f"{pct:.0f}%\n(n={n})",
            ha="center",
            fontsize=9,
            color=DARK,
        )
    ax3.set_xticks(x)
    ax3.set_xticklabels(tier_labels, rotation=15, ha="right")
    ax3.set_ylabel("Sites with ≥1 Tracker Cookie (%)", fontsize=11)
    ax3.set_title("Sites with ≥1 Tracker by Rank Tier", fontsize=13, pad=10)
    ax3.grid(axis="y", alpha=0.35)
    ax3.spines[["top", "right"]].set_visible(False)
    ax3.set_ylim(0, 115)

    fig.suptitle("Tracker Cookie Prevalence vs. Website Rank", fontsize=16, y=1.02)
    plt.tight_layout()
    save_figure(out_dir, "plot_trackers_vs_rank.png")

    print(f"\n{n_matched} sites matched. Saved to {out_dir}/plot_trackers_vs_rank.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument(
        "--rank",
        default="./list_websites_1M.csv",
        help="Path to the headerless rank CSV (rank,domain)",
    )
    parser.add_argument("--out", default="./plots/trackers")
    args = parser.parse_args()
    plot_trackers_vs_rank(args.data, args.rank, args.out)
