"""
Compare Tracking Cookies: EasyPrivacy vs OpenCookieDatabase

This script analyzes and compares how tracking cookies are flagged by two
different sources:
- EasyPrivacy (privacy filter list)
- OpenCookieDatabase (cookie classification database)

The analysis generates:
1. Venn diagram showing overlaps between both sources
2. Detailed comparison statistics (agreement, disagreement, etc.)
3. Per-tracker breakdown showing which cookies are flagged by each source
4. Summary statistics and discrepancy analysis

Usage:
    python scripts/plot_scripts/compare_tracker_sources.py --data cookies_data --out plots

Requirements:
    - Cookies collected with both EasyPrivacy and OpenCookieDatabase tracking lists
"""

import argparse
import os
import sys
from collections import defaultdict
from typing import Dict, List, Set, Tuple

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib_venn import venn2
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    dataset,
    save_figure,
    BG,
    DARK,
    ACCENT,
    ACCENT2,
    MID,
    LIGHT,
)


def load_tracker_data(data_dir: str) -> pd.DataFrame:
    """
    Load tracker cookies with per-source flags from the centralised dataset.

    Returns a DataFrame of tracker cookies with columns: domain, name,
    is_tracker_ep, is_tracker_ocd, is_tracker, flagged_by, party_type, session,
    lifetime_days. The EasyPrivacy / OpenCookieDatabase split comes straight from
    the enriched ``is_tracker_ep`` / ``is_tracker_ocd`` columns.
    """
    df = dataset(data_dir).cookies
    trackers = df[df["is_tracker"]].copy()
    if trackers.empty:
        raise ValueError(
            "No cookies with tracker information found. "
            "Re-collect with both tracker lists enabled."
        )

    def _flagged_by(row) -> str:
        sources = []
        if row["is_tracker_ep"]:
            sources.append("EasyPrivacy")
        if row["is_tracker_ocd"]:
            sources.append("OpenCookieDatabase")
        return ", ".join(sources)

    trackers["flagged_by"] = trackers.apply(_flagged_by, axis=1)
    out = trackers[
        [
            "domain",
            "name",
            "is_tracker_ep",
            "is_tracker_ocd",
            "is_tracker",
            "flagged_by",
            "party_type",
            "session",
            "lifetime_days",
        ]
    ].reset_index(drop=True)
    print(f"Loaded {len(out)} tracked cookies from {out['domain'].nunique()} domains")
    return out


def generate_statistics(df: pd.DataFrame) -> Dict:
    """Calculate detailed comparison statistics."""
    total = len(df)
    ep_only = (df["is_tracker_ep"] & ~df["is_tracker_ocd"]).sum()
    ocd_only = (~df["is_tracker_ep"] & df["is_tracker_ocd"]).sum()
    both = (df["is_tracker_ep"] & df["is_tracker_ocd"]).sum()

    ep_total = df["is_tracker_ep"].sum()
    ocd_total = df["is_tracker_ocd"].sum()

    # Agreement and disagreement rates
    agreement = both / total * 100 if total > 0 else 0
    disagreement = (ep_only + ocd_only) / total * 100 if total > 0 else 0

    # Coverage percentages
    ep_coverage = ep_total / total * 100 if total > 0 else 0
    ocd_coverage = ocd_total / total * 100 if total > 0 else 0

    # Overlap percentage
    overlap_pct = (
        both / max(ep_total, ocd_total) * 100 if max(ep_total, ocd_total) > 0 else 0
    )

    stats = {
        "total_tracked": total,
        "easyprivacy_only": ep_only,
        "opencookie_only": ocd_only,
        "both_sources": both,
        "easyprivacy_total": ep_total,
        "opencookie_total": ocd_total,
        "agreement_pct": agreement,
        "disagreement_pct": disagreement,
        "easyprivacy_coverage": ep_coverage,
        "opencookie_coverage": ocd_coverage,
        "overlap_pct": overlap_pct,
    }

    return stats


def print_summary_report(stats: Dict, df: pd.DataFrame) -> None:
    """Print a comprehensive summary report."""
    print("\n" + "=" * 70)
    print("TRACKER SOURCE COMPARISON REPORT")
    print("=" * 70)

    print(f"\nTotal Tracked Cookies Analyzed:     {stats['total_tracked']:>6,}")
    print(f"\nSource Breakdown:")
    print(
        f"  EasyPrivacy flags:                {stats['easyprivacy_total']:>6,} ({stats['easyprivacy_coverage']:.1f}%)"
    )
    print(
        f"  OpenCookieDatabase flags:         {stats['opencookie_total']:>6,} ({stats['opencookie_coverage']:.1f}%)"
    )
    print(f"\nAgreement Analysis:")
    print(
        f"  Flagged by both sources:          {stats['both_sources']:>6,} ({stats['agreement_pct']:.1f}%)"
    )
    print(f"  Flagged only by EasyPrivacy:      {stats['easyprivacy_only']:>6,}")
    print(f"  Flagged only by OpenCookieDB:     {stats['opencookie_only']:>6,}")
    print(f"  Overall disagreement:              {stats['disagreement_pct']:.1f}%")
    print(f"  Overlap between sources:           {stats['overlap_pct']:.1f}%")

    # Party type breakdown
    print(f"\nFirst vs Third-Party Breakdown:")
    first_party = df[df["party_type"] == "first_party"]
    third_party = df[df["party_type"] == "third_party"]

    if len(first_party) > 0:
        fp_ep = first_party["is_tracker_ep"].sum()
        fp_ocd = first_party["is_tracker_ocd"].sum()
        print(f"  First-party tracked:               {len(first_party):>6,}")
        print(f"    - EasyPrivacy:                   {fp_ep:>6,}")
        print(f"    - OpenCookieDB:                  {fp_ocd:>6,}")

    if len(third_party) > 0:
        tp_ep = third_party["is_tracker_ep"].sum()
        tp_ocd = third_party["is_tracker_ocd"].sum()
        print(f"  Third-party tracked:               {len(third_party):>6,}")
        print(f"    - EasyPrivacy:                   {tp_ep:>6,}")
        print(f"    - OpenCookieDB:                  {tp_ocd:>6,}")

    # Session vs Persistent
    print(f"\nSession vs Persistent Breakdown:")
    session = df[df["session"] == True]
    persistent = df[df["session"] == False]

    if len(session) > 0:
        s_ep = session["is_tracker_ep"].sum()
        s_ocd = session["is_tracker_ocd"].sum()
        print(f"  Session tracked cookies:           {len(session):>6,}")
        print(f"    - EasyPrivacy:                   {s_ep:>6,}")
        print(f"    - OpenCookieDB:                  {s_ocd:>6,}")

    if len(persistent) > 0:
        p_ep = persistent["is_tracker_ep"].sum()
        p_ocd = persistent["is_tracker_ocd"].sum()
        print(f"  Persistent tracked cookies:        {len(persistent):>6,}")
        print(f"    - EasyPrivacy:                   {p_ep:>6,}")
        print(f"    - OpenCookieDB:                  {p_ocd:>6,}")

    # Top disagreeing cookies
    print(f"\nTop 10 Most Commonly Disagreed-Upon Cookies:")
    disagreed = df[
        (df["is_tracker_ep"] & ~df["is_tracker_ocd"])
        | (~df["is_tracker_ep"] & df["is_tracker_ocd"])
    ]

    if len(disagreed) > 0:
        top_disagreed = disagreed["name"].value_counts().head(10)
        for i, (name, count) in enumerate(top_disagreed.items(), 1):
            # Check which source flags it
            ep_count = disagreed[
                (disagreed["name"] == name) & disagreed["is_tracker_ep"]
            ].shape[0]
            ocd_count = disagreed[
                (disagreed["name"] == name) & disagreed["is_tracker_ocd"]
            ].shape[0]
            source = "EP" if ep_count > 0 else "OCD"
            print(f"  {i:2}. {name:<40} ({count:>3} occurrences, {source})")

    print("\n" + "=" * 70)


def plot_venn_diagram(df: pd.DataFrame, out_dir: str) -> None:
    """Create Venn diagram comparing the two tracker sources."""
    apply_theme()

    # Get sets of tracked cookies
    ep_set = set(df[df["is_tracker_ep"]].index)
    ocd_set = set(df[df["is_tracker_ocd"]].index)

    fig, ax = plt.subplots(figsize=(10, 8))

    venn = venn2(
        [ep_set, ocd_set],
        set_labels=("EasyPrivacy", "OpenCookieDatabase"),
        ax=ax,
        set_colors=(ACCENT, ACCENT2),
        alpha=0.7,
    )

    # Customize text
    for text in venn.set_labels:
        text.set_fontsize(13)
        text.set_fontweight("bold")

    for text in venn.subset_labels:
        text.set_fontsize(12)
        text.set_fontweight("bold")

    ax.set_title(
        "Comparison of Tracked Cookies\nby EasyPrivacy vs OpenCookieDatabase",
        fontsize=14,
        fontweight="bold",
        pad=20,
    )

    save_figure(out_dir, "venn_tracker_sources.png")


def plot_comparison_bars(df: pd.DataFrame, out_dir: str) -> None:
    """Create bar chart comparing source coverage and agreement."""
    apply_theme()

    stats = generate_statistics(df)

    categories = ["EasyPrivacy", "OpenCookieDB", "Both Sources"]
    values = [
        stats["easyprivacy_total"],
        stats["opencookie_total"],
        stats["both_sources"],
    ]
    colors = [ACCENT, ACCENT2, MID]

    fig, ax = plt.subplots(figsize=(10, 6))

    bars = ax.bar(
        categories, values, color=colors, edgecolor=DARK, linewidth=2, alpha=0.8
    )

    # Add value labels on bars
    for bar, val in zip(bars, values):
        height = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            height,
            f"{int(val):,}",
            ha="center",
            va="bottom",
            fontweight="bold",
            fontsize=11,
        )

    ax.set_ylabel("Number of Tracked Cookies", fontweight="bold")
    ax.set_title("Tracker Detection Comparison by Source", fontweight="bold", pad=15)
    ax.grid(axis="y", alpha=0.3, linestyle="--")

    save_figure(out_dir, "comparison_bars.png")


def plot_party_type_comparison(df: pd.DataFrame, out_dir: str) -> None:
    """Create grouped bar chart comparing first vs third-party by source."""
    apply_theme()

    # Split by party type
    first_party = df[df["party_type"] == "first_party"]
    third_party = df[df["party_type"] == "third_party"]

    fp_ep = first_party["is_tracker_ep"].sum() if len(first_party) > 0 else 0
    fp_ocd = first_party["is_tracker_ocd"].sum() if len(first_party) > 0 else 0
    tp_ep = third_party["is_tracker_ep"].sum() if len(third_party) > 0 else 0
    tp_ocd = third_party["is_tracker_ocd"].sum() if len(third_party) > 0 else 0

    x = np.arange(2)
    width = 0.35

    fig, ax = plt.subplots(figsize=(10, 6))

    bars1 = ax.bar(
        x - width / 2,
        [fp_ep, tp_ep],
        width,
        label="EasyPrivacy",
        color=ACCENT,
        edgecolor=DARK,
        linewidth=1.5,
    )
    bars2 = ax.bar(
        x + width / 2,
        [fp_ocd, tp_ocd],
        width,
        label="OpenCookieDatabase",
        color=ACCENT2,
        edgecolor=DARK,
        linewidth=1.5,
    )

    ax.set_ylabel("Number of Tracked Cookies", fontweight="bold")
    ax.set_title(
        "Tracker Detection: First-Party vs Third-Party Cookies",
        fontweight="bold",
        pad=15,
    )
    ax.set_xticks(x)
    ax.set_xticklabels(["First-Party", "Third-Party"])
    ax.legend(loc="upper right", framealpha=0.9)
    ax.grid(axis="y", alpha=0.3, linestyle="--")

    # Add value labels
    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            if height > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    height,
                    f"{int(height):,}",
                    ha="center",
                    va="bottom",
                    fontweight="bold",
                    fontsize=10,
                )

    save_figure(out_dir, "comparison_party_type.png")


def export_detailed_csv(df: pd.DataFrame, out_dir: str) -> None:
    """Export detailed comparison data to CSV for further analysis."""
    os.makedirs(out_dir, exist_ok=True)

    # Separate different categories
    both = df[df["is_tracker_ep"] & df["is_tracker_ocd"]]
    ep_only = df[df["is_tracker_ep"] & ~df["is_tracker_ocd"]]
    ocd_only = df[~df["is_tracker_ep"] & df["is_tracker_ocd"]]

    # Export each category
    categories = {
        "tracked_by_both_sources": both,
        "tracked_by_easyprivacy_only": ep_only,
        "tracked_by_opencookie_only": ocd_only,
    }

    for name, data in categories.items():
        if len(data) > 0:
            out_path = os.path.join(out_dir, f"{name}.csv")
            data.to_csv(out_path, index=False)
            print(f"Exported {len(data):>6} rows → {out_path}")


def main(data_dir: str, out_dir: str) -> None:
    """Main analysis pipeline."""
    print("\nLoading cookie data with tracker information...")
    df = load_tracker_data(data_dir)

    print("\nGenerating statistics...")
    stats = generate_statistics(df)

    print("\nGenerating summary report...")
    print_summary_report(stats, df)

    print("\nGenerating visualizations...")
    plot_venn_diagram(df, out_dir)
    plot_comparison_bars(df, out_dir)
    plot_party_type_comparison(df, out_dir)

    print("\nExporting detailed data...")
    export_detailed_csv(df, out_dir)

    print("\n✓ Analysis complete!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compare tracking cookies flagged by EasyPrivacy vs OpenCookieDatabase"
    )
    parser.add_argument(
        "--data",
        default="./cookies_data",
        help="Path to cookies data directory",
    )
    parser.add_argument(
        "--out",
        default="./plots/comparison",
        help="Path to output directory for plots and data",
    )
    args = parser.parse_args()

    main(args.data, args.out)
