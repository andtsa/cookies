"""
Cross-Browser Cookie Comparison

Compares key cookie metrics across browser engines (Chromium, WebKit, Firefox,
etc.) for the same set of websites. Requires data collected under
cookies_data/{browser}/ subdirectories.

Metrics compared:
  - Average total cookies per site
  - Session vs. persistent ratio
  - Tracker share (if is_tracker is present)
  - Average lifetime of persistent cookies

Usage:
    python scripts/plot_scripts/plot_cross_browser.py --data cookies_data --out plots/cross_browser
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
    load_cookie_data,
    save_figure,
    COLORS,
    BG,
    DARK,
    MID,
    LIGHT,
    ACCENT,
)

BROWSER_COLORS = {
    "chromium": COLORS[0],
    "chrome": COLORS[0],
    "webkit": COLORS[1],
    "safari": COLORS[1],
    "firefox": COLORS[2],
    "brave": COLORS[3],
    "duckduckgo": COLORS[4],
    "unknown": COLORS[5],
}


def browser_color(name: str) -> str:
    return BROWSER_COLORS.get(name.lower(), COLORS[len(BROWSER_COLORS) % len(COLORS)])


def _to_bool_tracker(val) -> bool:
    if val is None or val is False:
        return False
    return bool(val) if isinstance(val, bool) else bool((val or {}).get("lists"))


def plot_cross_browser(data_dir: str, out_dir: str) -> None:
    apply_theme()
    sites_df, cookies_df = load_cookie_data(data_dir)

    browsers = sorted(cookies_df["browser"].unique())
    if len(browsers) < 2:
        print(
            f"Only one browser found ({browsers}). "
            "Collect data from multiple browsers to enable this comparison."
        )
        return

    colors = [browser_color(b) for b in browsers]

    # ── Per-browser site-level stats ──────────────────────────────────────
    site_stats = (
        sites_df.groupby("browser")
        .agg(
            n_sites=("domain", "count"),
            avg_total_cookies=("total_cookies", "mean"),
            avg_session=("num_session", "mean"),
            avg_persistent=("num_persistent", "mean"),
            avg_lifetime=("avg_lifetime_days", "mean"),
        )
        .reindex(browsers)
    )

    # ── Per-browser cookie-level tracker stats ────────────────────────────
    has_tracker = "is_tracker" in cookies_df.columns
    if has_tracker:
        cookies_df["is_tracker_bool"] = cookies_df["is_tracker"].apply(_to_bool_tracker)
        tracker_stats = (
            cookies_df.groupby("browser")["is_tracker_bool"].mean().reindex(browsers)
            * 100
        )

    x = np.arange(len(browsers))
    width = 0.55

    n_plots = 4 if has_tracker else 3
    fig, axes = plt.subplots(1, n_plots, figsize=(4 * n_plots + 1, 6))

    def _bar(ax, values, title, ylabel, fmt="{:.1f}"):
        bars = ax.bar(
            x, values, color=colors, edgecolor=BG, linewidth=0.8, width=width, alpha=0.9
        )
        for bar, val in zip(bars, values):
            if not np.isnan(val):
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + max(values) * 0.02,
                    fmt.format(val),
                    ha="center",
                    va="bottom",
                    fontsize=10,
                    color=DARK,
                )
        ax.set_xticks(x)
        ax.set_xticklabels([b.capitalize() for b in browsers], rotation=15, ha="right")
        ax.set_title(title, fontsize=12, pad=10)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.grid(axis="y", alpha=0.35)
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_ylim(0, max(values) * 1.25 if max(values) > 0 else 1)

    _bar(
        axes[0],
        site_stats["avg_total_cookies"].fillna(0).tolist(),
        "Avg. Cookies per Site",
        "Cookies",
    )

    # Session vs persistent stacked
    ax_sp = axes[1]
    sess_vals = site_stats["avg_session"].fillna(0).tolist()
    pers_vals = site_stats["avg_persistent"].fillna(0).tolist()
    ax_sp.bar(
        x,
        sess_vals,
        color=COLORS[5],
        label="Session",
        edgecolor=BG,
        linewidth=0.8,
        width=width,
        alpha=0.9,
    )
    ax_sp.bar(
        x,
        pers_vals,
        bottom=sess_vals,
        color=COLORS[0],
        label="Persistent",
        edgecolor=BG,
        linewidth=0.8,
        width=width,
        alpha=0.9,
    )
    ax_sp.set_xticks(x)
    ax_sp.set_xticklabels([b.capitalize() for b in browsers], rotation=15, ha="right")
    ax_sp.set_title("Session vs. Persistent Cookies", fontsize=12, pad=10)
    ax_sp.set_ylabel("Avg. Cookies per Site")
    ax_sp.legend(fontsize=9)
    ax_sp.grid(axis="y", alpha=0.35)
    ax_sp.spines[["top", "right"]].set_visible(False)

    _bar(
        axes[2],
        site_stats["avg_lifetime"].fillna(0).tolist(),
        "Avg. Lifetime (Persistent)",
        "Days",
    )

    if has_tracker:
        _bar(
            axes[3],
            tracker_stats.fillna(0).tolist(),
            "Tracker Cookie Share",
            "% of Cookies",
            fmt="{:.1f}%",
        )

    # Footer: sample size
    for browser, row in site_stats.iterrows():
        pass  # just checking

    fig.suptitle("Cross-Browser Cookie Comparison", fontsize=16, y=1.02)
    plt.tight_layout()
    save_figure(out_dir, "plot_cross_browser.png")

    # Print summary table
    print("\nCross-browser summary:")
    print(f"{'Browser':<14} {'Sites':>6} {'Avg cookies':>12} {'Avg lifetime':>13}")
    print("-" * 50)
    for b in browsers:
        row = site_stats.loc[b]
        print(
            f"{b:<14} {int(row['n_sites']):>6} {row['avg_total_cookies']:>12.1f} "
            f"{row['avg_lifetime']:>13.1f}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--out", default="./plots/cross_browser")
    args = parser.parse_args()
    plot_cross_browser(args.data, args.out)
