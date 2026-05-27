"""
Sites with At Least One Tracker

Counts how many crawled websites have at least one cookie flagged as a tracker
(of any type / list) and visualises the result as:

  1. A large donut showing the tracked vs. clean split (site-level, not cookie-level).
  2. A horizontal bar chart breaking down tracker type/source for sites that
     have trackers (how many sites were flagged by EasyPrivacy, OpenCookieDB,
     both, or just "any" flag set).

Usage:
    python scripts/plot_scripts/plot_sites_with_tracker.py --data cookies_data --out plots/trackers
"""

import argparse
import os
import sys

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

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
    BUCKET_COLORS,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_tracker(val) -> bool:
    """Return True if the is_tracker field indicates a tracker cookie."""
    if val is None or val is False:
        return False
    if isinstance(val, bool):
        return val
    # dict schema: {"lists": [...], ...}
    if isinstance(val, dict):
        return bool(val.get("lists"))
    return False


def _tracker_lists(val) -> list[str]:
    """Return the list names that flagged this cookie, or empty list."""
    if isinstance(val, dict):
        return val.get("lists") or []
    return []


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_site_tracker_summary(data_dir: str) -> pd.DataFrame:
    """
    One row per unique site (registered_domain).

    Columns:
        site            – domain string
        total_cookies   – total cookies found
        n_tracker       – cookies flagged as a tracker (any list)
        has_tracker     – bool: site has ≥1 tracker cookie
        lists_seen      – frozenset of tracker list names seen on this site
    """
    rows: dict[str, dict] = {}

    for domain, browser, data in _iter_cookie_files(data_dir):
        # Use the site key from the JSON if available, else fall back to filename domain
        site = data.get("target_url") or domain
        # Normalise: strip scheme/path so different browsers collapse to same key
        import tldextract

        registered = tldextract.extract(site).registered_domain or domain
        if not registered:
            registered = domain

        cookies = data.get("cookies", [])
        if not cookies:
            continue

        # Skip files where is_tracker was never set (collected without --tracker-lists)
        if not any("is_tracker" in c for c in cookies):
            continue

        if registered not in rows:
            rows[registered] = {
                "site": registered,
                "total_cookies": 0,
                "n_tracker": 0,
                "lists_seen": set(),
            }

        rec = rows[registered]
        for cookie in cookies:
            if "is_tracker" not in cookie:
                continue
            rec["total_cookies"] += 1
            val = cookie["is_tracker"]
            if _is_tracker(val):
                rec["n_tracker"] += 1
                for lst in _tracker_lists(val):
                    rec["lists_seen"].add(lst)

    df = pd.DataFrame(list(rows.values()))
    if df.empty:
        return df

    df["has_tracker"] = df["n_tracker"] > 0
    df["lists_seen"] = df["lists_seen"].apply(frozenset)
    return df


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------


def plot_sites_with_tracker(data_dir: str, out_dir: str) -> None:
    apply_theme()

    print("Loading site tracker data…")
    df = load_site_tracker_summary(data_dir)

    if df.empty:
        print(
            "No is_tracker data found. "
            "Re-collect with --tracker-lists to annotate cookies."
        )
        return

    total_sites = len(df)
    n_tracked = int(df["has_tracker"].sum())
    n_clean = total_sites - n_tracked
    pct_tracked = n_tracked / total_sites * 100
    pct_clean = 100 - pct_tracked

    print(f"  Total sites analysed : {total_sites:,}")
    print(f"  Sites with ≥1 tracker: {n_tracked:,}  ({pct_tracked:.1f}%)")
    print(f"  Clean sites          : {n_clean:,}  ({pct_clean:.1f}%)")

    # ── Collect all unique tracker-list names across the whole dataset ────────
    all_lists: set[str] = set()
    for s in df[df["has_tracker"]]["lists_seen"]:
        all_lists.update(s)

    has_list_breakdown = bool(all_lists)

    # ── Figure layout ─────────────────────────────────────────────────────────
    if has_list_breakdown:
        fig, (ax_donut, ax_bar) = plt.subplots(1, 2, figsize=(14, 6))
    else:
        fig, ax_donut = plt.subplots(1, 1, figsize=(7, 6))

    # ── 1. Donut ──────────────────────────────────────────────────────────────
    values = [pct_tracked, pct_clean]
    colors = [ACCENT, COLORS[8]]  # warm red-orange vs soft beige

    wedges, _ = ax_donut.pie(
        values,
        colors=colors,
        startangle=90,
        wedgeprops={"width": 0.52, "edgecolor": BG, "linewidth": 2.5},
    )

    # Centre text
    ax_donut.text(
        0,
        0.08,
        f"{n_tracked:,}",
        ha="center",
        va="center",
        fontsize=22,
        fontweight="bold",
        color=ACCENT,
    )
    ax_donut.text(
        0,
        -0.22,
        "sites with\n≥1 tracker",
        ha="center",
        va="center",
        fontsize=11,
        color=DARK,
    )

    # Leader-line annotations
    label_info = [
        ("Has tracker", pct_tracked, n_tracked, ACCENT),
        ("No tracker", pct_clean, n_clean, COLORS[7]),
    ]
    for i, (label, pct, count, color) in enumerate(label_info):
        angle = (wedges[i].theta2 + wedges[i].theta1) / 2
        x_tip = 0.94 * np.cos(np.deg2rad(angle))
        y_tip = 0.94 * np.sin(np.deg2rad(angle))
        x_lbl = 1.30 * np.cos(np.deg2rad(angle))
        y_lbl = 1.30 * np.sin(np.deg2rad(angle))
        ax_donut.annotate(
            f"{label}\n{pct:.1f}%  ({count:,})",
            xy=(x_tip, y_tip),
            xytext=(x_lbl, y_lbl),
            ha="center",
            va="center",
            fontsize=11,
            fontweight="bold",
            color=color,
            arrowprops=dict(arrowstyle="-", color=MID, lw=1.2),
        )

    ax_donut.set_title(
        f"Sites with ≥1 Tracker Cookie\n(n = {total_sites:,} sites)",
        pad=18,
        fontsize=14,
    )

    # ── 2. Bar breakdown by tracker list ─────────────────────────────────────
    if has_list_breakdown:
        # Count how many sites were flagged by each list (sites can appear in multiple)
        list_counts: dict[str, int] = {}
        for lst in sorted(all_lists):
            list_counts[lst] = int(df["lists_seen"].apply(lambda s: lst in s).sum())

        # Sort descending
        sorted_lists = sorted(list_counts.items(), key=lambda x: x[1], reverse=True)
        labels = [l for l, _ in sorted_lists]
        counts = [c for _, c in sorted_lists]
        bar_colors = [COLORS[i % len(COLORS)] for i in range(len(labels))]

        y_pos = np.arange(len(labels))
        bars = ax_bar.barh(
            y_pos,
            counts,
            color=bar_colors,
            edgecolor=BG,
            linewidth=0.7,
            height=0.6,
        )
        ax_bar.invert_yaxis()
        ax_bar.set_yticks(y_pos)
        ax_bar.set_yticklabels(labels, fontsize=11)

        for bar, count in zip(bars, counts):
            pct = count / total_sites * 100
            ax_bar.text(
                bar.get_width() + 0.3,
                bar.get_y() + bar.get_height() / 2,
                f"{count:,}  ({pct:.1f}%)",
                va="center",
                fontsize=10,
                color=DARK,
            )

        ax_bar.set_xlabel("Number of Sites", fontsize=12)
        ax_bar.set_title("Sites Flagged by Each Tracker List", pad=12, fontsize=14)
        ax_bar.spines[["top", "right"]].set_visible(False)
        ax_bar.grid(axis="x", alpha=0.35)
        # Leave some room for the count labels
        ax_bar.set_xlim(0, max(counts) * 1.30)

        ax_bar.text(
            0.01,
            -0.10,
            f"Sites can appear in multiple lists. Total sites: {total_sites:,}",
            transform=ax_bar.transAxes,
            fontsize=8.5,
            color=MID,
        )

    fig.suptitle("Tracker Prevalence Across Crawled Websites", fontsize=16, y=1.02)
    plt.tight_layout()
    save_figure(out_dir, "plot_sites_with_tracker.png", "plot_sites_with_tracker.pdf")
    print(f"  Saved to {out_dir}/plot_sites_with_tracker.png")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Plot: how many crawled websites have at least one tracker cookie "
            "(of any type/list)."
        )
    )
    parser.add_argument(
        "--data",
        default="./cookies_data",
        help="Directory containing the raw cookie JSON files.",
    )
    parser.add_argument(
        "--out",
        default="./plots/trackers",
        help="Directory to write the output plot(s) into.",
    )
    args = parser.parse_args()
    plot_sites_with_tracker(args.data, args.out)
