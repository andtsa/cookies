"""
Tracker Count vs. Website Popularity Rank

Joins ``CookieDataset.cookies`` (which already carries ``is_tracker``,
``registered_domain``, and the per-cookie rank from the crawl context) with an
optional external rank CSV to correlate website popularity with the *number* of
tracker cookies a visitor encounters.

The ``sites`` frame from ``CookieDataset`` already contains a ``rank`` column
embedded during the crawl (``crawl_context.rank``). When that is populated the
``--rank`` CSV is unnecessary; when it is absent the script falls back to joining
against the CSV exactly like ``plot_trackers_vs_rank.py`` does.

Views produced:
  1. Scatter — rank (log-scale x) vs. tracker cookie count (y),
     coloured by % tracker share, with a log-fit trend line.
  2. Mean tracker count per rank tier (bar chart).
  3. Median + IQR per rank tier (box-style bar) so distribution shape is visible.

Usage:
    python3 scripts/plot_scripts/plot_tracker_count_vs_rank.py \\
        --data cookies_data [--rank list_websites_1M.csv] --out plots/trackers
"""

import argparse
import csv
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from scripts.plot_scripts.utils import *

# Must match the tiers defined in analysis/access/frames.py so labels are consistent.
RANK_TIERS = [
    (1, 10, "Top 10"),
    (11, 50, "Top 50"),
    (51, 100, "Top 100"),
    (101, 1_000, "101–1k"),
    (1_001, 10_000, "1k–10k"),
    (10_001, 100_000, "10k–100k"),
    (100_001, 1_000_000, "100k–1M"),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_rank_csv(rank_csv: str) -> dict[str, int]:
    """Return {registered_domain -> rank} from a headerless rank CSV."""
    from analysis.src.helpers import registered_domain as reg_domain

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
            rd = reg_domain(domain) or domain
            if rd:
                ranks[rd] = rank
    return ranks


# ---------------------------------------------------------------------------
# Data loading — uses the new CookieDataset API
# ---------------------------------------------------------------------------


def load_site_tracker_counts(data_dir: str, rank_csv: str | None) -> pd.DataFrame:
    """
    Return a site-level DataFrame with columns:
        registered_domain, total_cookies, n_tracker, pct_trackers, has_tracker, rank

    Rank comes from ``CookieDataset.sites`` (``crawl_context.rank``).
    If that column is missing or sparse, falls back to joining the external CSV.
    """
    ds = dataset(data_dir)
    cookies = ds.classified_cookies

    if cookies.empty or "is_tracker" not in cookies.columns:
        return pd.DataFrame()

    annotated = cookies[cookies["is_tracker"].notna()].copy()
    annotated["is_tracker"] = annotated["is_tracker"].astype(bool)

    # Site-level aggregation from the cookies frame
    grp = annotated.groupby("registered_domain")
    site_df = pd.DataFrame(
        {
            "total_cookies": grp["is_tracker"].count(),
            "n_tracker": grp["is_tracker"].sum(),
        }
    ).reset_index()
    site_df["pct_trackers"] = np.where(
        site_df["total_cookies"] > 0,
        site_df["n_tracker"] / site_df["total_cookies"] * 100,
        0.0,
    )
    site_df["has_tracker"] = site_df["n_tracker"] > 0

    # Try to get rank from the sites frame first
    sites_frame = ds.sites
    if "rank" in sites_frame.columns and sites_frame["rank"].notna().any():
        rank_map = (
            sites_frame[sites_frame["rank"].notna()]
            .groupby("registered_domain")["rank"]
            .min()
        )
        site_df["rank"] = site_df["registered_domain"].map(rank_map)

    # Fall back to external CSV if rank column is absent or fully null
    if "rank" not in site_df.columns or site_df["rank"].isna().all():
        if rank_csv and os.path.isfile(rank_csv):
            print(f"  Rank column absent in sites frame — loading from {rank_csv}")
            ranks = _load_rank_csv(rank_csv)
            site_df["rank"] = site_df["registered_domain"].map(ranks)
        else:
            site_df["rank"] = pd.NA

    return site_df


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------


def plot_tracker_count_vs_rank(
    data_dir: str, rank_csv: str | None, out_dir: str
) -> None:
    apply_theme()

    print("Loading site cookie data…")
    df = load_site_tracker_counts(data_dir, rank_csv)

    if df.empty:
        print("No is_tracker data found. Re-collect with --tracker-lists.")
        return

    matched = df.dropna(subset=["rank"]).copy()
    matched["rank"] = matched["rank"].astype(int)

    n_matched = len(matched)
    n_unmatched = len(df) - n_matched
    print(
        f"  {len(df):,} sites total; {n_matched:,} matched to ranks ({n_unmatched:,} unmatched)"
    )

    if matched.empty:
        print(
            "No sites could be matched to a rank. "
            "Ensure the crawl embedded rank in crawl_context, or pass --rank."
        )
        return

    # ── Tier aggregation ─────────────────────────────────────────────────
    tier_labels, tier_means, tier_medians, tier_q1, tier_q3, tier_ns = (
        [],
        [],
        [],
        [],
        [],
        [],
    )
    for lo, hi, label in RANK_TIERS:
        sub = matched[(matched["rank"] >= lo) & (matched["rank"] <= hi)]
        if len(sub) == 0:
            continue
        tier_labels.append(label)
        tier_means.append(sub["n_tracker"].mean())
        tier_medians.append(sub["n_tracker"].median())
        tier_q1.append(sub["n_tracker"].quantile(0.25))
        tier_q3.append(sub["n_tracker"].quantile(0.75))
        tier_ns.append(len(sub))

    n_tiers = len(tier_labels)
    x = np.arange(n_tiers)

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    # ── 1. Scatter: rank (log) vs tracker count, colour = % share ────────
    ax = axes[0]
    sc = ax.scatter(
        matched["rank"],
        matched["n_tracker"],
        c=matched["pct_trackers"],
        cmap="YlOrRd",
        alpha=0.50,
        s=16,
        edgecolors="none",
        vmin=0,
        vmax=100,
    )
    cbar = fig.colorbar(sc, ax=ax, pad=0.02)
    cbar.set_label("% Tracker Cookies", fontsize=9, color=DARK)
    cbar.ax.yaxis.set_tick_params(color=DARK)
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color=DARK)

    log_rank = np.log10(matched["rank"])
    z = np.polyfit(log_rank, matched["n_tracker"], 1)
    p = np.poly1d(z)
    x_line = np.linspace(log_rank.min(), log_rank.max(), 300)
    ax.plot(
        10**x_line,
        p(x_line),
        color=DARK,
        linewidth=1.8,
        linestyle="--",
        label="trend (log fit)",
    )

    ax.set_xscale("log")
    ax.set_xlabel("Website Rank (log scale)", fontsize=11)
    ax.set_ylabel("# Tracker Cookies per Site", fontsize=11)
    ax.set_title("Tracker Count vs. Rank", fontsize=13, pad=10)
    ax.legend(fontsize=9)
    ax.grid(alpha=0.28)
    ax.spines[["top", "right"]].set_visible(False)

    # ── 2. Mean tracker count per rank tier ──────────────────────────────
    ax2 = axes[1]
    bars = ax2.bar(
        x,
        tier_means,
        color=COLORS[:n_tiers],
        edgecolor=BG,
        linewidth=0.8,
        alpha=0.92,
        width=0.62,
    )
    for bar, mean, n in zip(bars, tier_means, tier_ns):
        ax2.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(tier_means) * 0.015,
            f"{mean:.1f}\n(n={n})",
            ha="center",
            fontsize=8.5,
            color=DARK,
        )
    ax2.set_xticks(x)
    ax2.set_xticklabels(tier_labels, rotation=15, ha="right")
    ax2.set_ylabel("Mean # Tracker Cookies", fontsize=11)
    ax2.set_title("Mean Tracker Count by Rank Tier", fontsize=13, pad=10)
    ax2.grid(axis="y", alpha=0.32)
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.set_ylim(0, max(tier_means) * 1.30 if tier_means else 1)

    # ── 3. Median + IQR per rank tier ────────────────────────────────────
    ax3 = axes[2]
    ax3.bar(
        x,
        [q3 - q1 for q3, q1 in zip(tier_q3, tier_q1)],
        bottom=tier_q1,
        color=ACCENT2,
        edgecolor=BG,
        linewidth=0.7,
        alpha=0.55,
        width=0.62,
        label="IQR (25th–75th %ile)",
    )
    ax3.bar(
        x,
        [0.35] * n_tiers,
        bottom=[m - 0.175 for m in tier_medians],
        color=ACCENT,
        edgecolor=BG,
        linewidth=0.5,
        alpha=0.95,
        width=0.62,
        label="Median",
        zorder=3,
    )

    for i, (med, n) in enumerate(zip(tier_medians, tier_ns)):
        ax3.text(
            i,
            tier_q3[i] + max(tier_q3) * 0.02,
            f"med={med:.0f}\n(n={n})",
            ha="center",
            fontsize=8.5,
            color=DARK,
        )

    ax3.set_xticks(x)
    ax3.set_xticklabels(tier_labels, rotation=15, ha="right")
    ax3.set_ylabel("# Tracker Cookies (Median + IQR)", fontsize=11)
    ax3.set_title("Tracker Count Distribution by Rank Tier", fontsize=13, pad=10)
    ax3.legend(fontsize=9, loc="upper right")
    ax3.grid(axis="y", alpha=0.32)
    ax3.spines[["top", "right"]].set_visible(False)
    ax3.set_ylim(0, max(tier_q3) * 1.35 if tier_q3 else 1)

    fig.suptitle(
        "Tracker Cookie Count vs. Website Popularity",
        fontsize=16,
        fontweight="bold",
        y=1.02,
    )
    plt.tight_layout()
    save_figure(
        out_dir, "plot_tracker_count_vs_rank.png", "plot_tracker_count_vs_rank.pdf"
    )
    print(
        f"\n{n_matched} sites matched. Saved to {out_dir}/plot_tracker_count_vs_rank.png"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Plot tracker cookie count vs. website popularity rank — "
            "scatter, mean per tier, and median+IQR per tier."
        )
    )
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument(
        "--rank",
        default=None,
        help=(
            "Path to a headerless rank CSV (rank,domain). "
            "Optional if the crawl embedded rank in crawl_context."
        ),
    )
    parser.add_argument("--out", default="./plots/trackers")
    args = parser.parse_args()
    plot_tracker_count_vs_rank(args.data, args.rank, args.out)
