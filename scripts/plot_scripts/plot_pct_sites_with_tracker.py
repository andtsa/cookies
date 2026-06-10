"""
Percentage of Webpages with At Least One Tracker

Shows what fraction of crawled websites have at least one cookie flagged as a
tracker, visualised as:

  1. A large donut — tracked vs. clean sites (site-level, not cookie-level).
  2. A horizontal bar breakdown — how many sites each tracker source caught
     (EasyPrivacy only, OpenCookieDB only, both, or other), as % of all sites.

Data comes from ``CookieDataset.cookies`` (the canonical enriched frame), which
already carries ``is_tracker``, ``is_tracker_ep``, ``is_tracker_ocd``, and
``registered_domain`` — no manual JSON iteration needed.

Usage:
    python scripts/plot_scripts/plot_pct_sites_with_tracker.py \\
        --data cookies_data --out plots/trackers
"""

import argparse
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    dataset,
    save_figure,
    BG,
    DARK,
    MID,
    LIGHT,
    ACCENT,
    ACCENT2,
    COLORS,
)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_site_tracker_summary(data_dir: str) -> pd.DataFrame:
    """
    Build a site-level summary from ``CookieDataset.cookies``.

    Returns one row per ``registered_domain`` with columns:
        total_cookies, n_tracker, has_tracker,
        has_easyprivacy, has_ocdb, has_both, has_only_ep, has_only_ocdb, has_other
    """
    cookies = dataset(data_dir).cookies

    if cookies.empty:
        return pd.DataFrame()

    # Only keep rows where tracker annotation is present
    if "is_tracker" not in cookies.columns:
        return pd.DataFrame()

    annotated = cookies[cookies["is_tracker"].notna()].copy()
    if annotated.empty:
        return pd.DataFrame()

    # Coerce boolean columns defensively
    for col in ("is_tracker", "is_tracker_ep", "is_tracker_ocd"):
        if col in annotated.columns:
            annotated[col] = annotated[col].astype(bool)
        else:
            annotated[col] = False

    grp = annotated.groupby("registered_domain")

    df = pd.DataFrame(
        {
            "total_cookies": grp["is_tracker"].count(),
            "n_tracker": grp["is_tracker"].sum(),
            "has_easyprivacy": grp["is_tracker_ep"].any(),
            "has_ocdb": grp["is_tracker_ocd"].any(),
        }
    ).reset_index()

    df["has_tracker"] = df["n_tracker"] > 0
    df["has_both"] = df["has_easyprivacy"] & df["has_ocdb"]
    df["has_only_ep"] = df["has_easyprivacy"] & ~df["has_ocdb"]
    df["has_only_ocdb"] = df["has_ocdb"] & ~df["has_easyprivacy"]
    df["has_other"] = df["has_tracker"] & ~df["has_easyprivacy"] & ~df["has_ocdb"]

    return df


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------


def plot_pct_sites_with_tracker(data_dir: str, out_dir: str) -> None:
    apply_theme()

    print("Loading site tracker data…")
    df = load_site_tracker_summary(data_dir)

    if df.empty:
        print(
            "No is_tracker data found. "
            "Re-collect with --tracker-lists to annotate cookies."
        )
        return

    n_total = len(df)
    n_tracked = int(df["has_tracker"].sum())
    n_clean = n_total - n_tracked
    pct_tracked = n_tracked / n_total * 100
    pct_clean = n_clean / n_total * 100

    print(f"  Total sites:   {n_total:,}")
    print(f"  With tracker:  {n_tracked:,}  ({pct_tracked:.1f}%)")
    print(f"  Clean:         {n_clean:,}  ({pct_clean:.1f}%)")

    fig = plt.figure(figsize=(14, 7))
    ax_donut = fig.add_axes([0.03, 0.08, 0.42, 0.84])
    ax_bar = fig.add_axes([0.52, 0.12, 0.44, 0.72])

    # ── 1. Donut ──────────────────────────────────────────────────────────
    wedges = ax_donut.pie(
        [pct_tracked, pct_clean],
        colors=[ACCENT, LIGHT],
        startangle=90,
        wedgeprops={"width": 0.52, "edgecolor": BG, "linewidth": 2.5},
    )[0]

    ax_donut.text(
        0,
        0.08,
        f"{pct_tracked:.1f}%",
        ha="center",
        va="center",
        fontsize=26,
        fontweight="bold",
        color=ACCENT,
    )
    ax_donut.text(
        0,
        -0.22,
        "of sites have\na tracker cookie",
        ha="center",
        va="center",
        fontsize=11,
        color=DARK,
    )

    for i, (wedge, label, pct, count) in enumerate(
        zip(
            wedges,
            ["Has ≥1 Tracker", "No Trackers"],
            [pct_tracked, pct_clean],
            [n_tracked, n_clean],
        )
    ):
        angle = (wedge.theta2 + wedge.theta1) / 2
        cos_a = np.cos(np.deg2rad(angle))
        sin_a = np.sin(np.deg2rad(angle))
        ax_donut.annotate(
            f"{label}\n{pct:.1f}%  (n={count:,})",
            xy=(0.72 * cos_a, 0.72 * sin_a),
            xytext=(1.22 * cos_a, 1.22 * sin_a),
            ha="center",
            va="center",
            fontsize=11,
            fontweight="bold",
            color=DARK,
            arrowprops=dict(arrowstyle="-", color=MID, lw=1.2),
        )

    ax_donut.set_title(
        f"Sites with ≥1 Tracker Cookie\n(n = {n_total:,} crawled sites)",
        fontsize=14,
        pad=14,
        color=DARK,
    )

    # ── 2. Breakdown bar ─────────────────────────────────────────────────
    tracked_df = df[df["has_tracker"]]
    raw_pairs = [
        ("Any tracker list", n_tracked, ACCENT),
        ("EasyPrivacy only", int(tracked_df["has_only_ep"].sum()), COLORS[0]),
        ("OpenCookieDB only", int(tracked_df["has_only_ocdb"].sum()), COLORS[1]),
        ("Both lists", int(tracked_df["has_both"].sum()), COLORS[2]),
        ("Other / unknown list", int(tracked_df["has_other"].sum()), COLORS[3]),
    ]
    pairs = [(l, c, col) for l, c, col in raw_pairs if c > 0]
    bl, bc, bcolors = zip(*pairs) if pairs else ([], [], [])

    pct_of_total = [c / n_total * 100 for c in bc]
    y = np.arange(len(bl))
    max_w = max(pct_of_total) if pct_of_total else 1

    bars = ax_bar.barh(
        y,
        pct_of_total,
        color=bcolors,
        edgecolor=BG,
        linewidth=0.7,
        height=0.58,
        alpha=0.92,
    )
    ax_bar.invert_yaxis()

    for bar, pct, cnt in zip(bars, pct_of_total, bc):
        ax_bar.text(
            bar.get_width() + max_w * 0.015,
            bar.get_y() + bar.get_height() / 2,
            f"{pct:.1f}%  ({cnt:,} sites)",
            va="center",
            fontsize=10,
            color=DARK,
        )

    ax_bar.set_yticks(y)
    ax_bar.set_yticklabels(bl, fontsize=11)
    ax_bar.set_xlabel("% of all crawled sites", fontsize=11)
    ax_bar.set_xlim(0, max_w * 1.50)
    ax_bar.set_title("Tracker Breakdown by Source List", fontsize=13, pad=10)
    ax_bar.spines[["top", "right"]].set_visible(False)
    ax_bar.grid(axis="x", alpha=0.3)

    fig.suptitle("Webpage Tracker Prevalence", fontsize=17, fontweight="bold", y=1.01)
    save_figure(
        out_dir, "plot_pct_sites_with_tracker.png", "plot_pct_sites_with_tracker.pdf"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Plot the percentage of crawled webpages that have at least one "
            "tracker cookie, with a breakdown by tracker source list."
        )
    )
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--out", default="./plots/trackers")
    args = parser.parse_args()
    plot_pct_sites_with_tracker(args.data, args.out)
