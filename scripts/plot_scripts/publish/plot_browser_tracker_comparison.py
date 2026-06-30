"""
Browser tracker comparison table.

Compares browsers within a single country: number of websites crawled, total
tracker cookies, unique tracker providers, and average tracker cookies per site.

Trackers use the unified ``is_tracker`` from ``CookieDataset.classified_cookies``
(``tracker_tier >= "probable"``). The dataset goes through the cached
``dataset()`` factory, so it is rank-capped (see ``COOKIE_RANK_CAP``) and reuses
the warmed annotation cache.

Outputs (per country):
    browser_tracker_comparison_<country>.png / .pdf
    browser_tracker_comparison_<country>_white.png / .pdf
"""

import argparse
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from scripts.plot_scripts.utils import *


def build_summary(cookies: pd.DataFrame) -> pd.DataFrame:
    trackers = cookies[cookies["is_tracker"]].copy()
    trackers["_provider"] = trackers["setter_domain"].fillna(
        trackers["cookie_domain"].str.lstrip(".")
    )

    summary = (
        trackers.groupby("browser")
        .agg(
            websites=("domain", "nunique"),
            tracker_cookies=("is_tracker", "size"),
            unique_trackers=("_provider", "nunique"),
        )
        .reset_index()
    )
    summary["avg_trackers_per_site"] = (
        summary["tracker_cookies"] / summary["websites"]
    ).round(1)
    summary = summary.sort_values("avg_trackers_per_site", ascending=False)
    summary.columns = [
        "Browser",
        "Websites",
        "Tracker Cookies",
        "Unique Trackers",
        "Avg. Trackers / Site",
    ]
    return summary


def draw_table(summary: pd.DataFrame, country: str, bg: str):
    apply_theme()
    if bg == "white":
        plt.rcParams.update(
            {
                "figure.facecolor": "white",
                "axes.facecolor": "white",
                "savefig.facecolor": "white",
                "text.color": "#222222",
                "axes.titlecolor": "#222222",
            }
        )

    fig_height = max(2.5, 0.75 * (len(summary) + 2))
    fig, ax = plt.subplots(figsize=(10, fig_height))
    ax.axis("off")

    table = ax.table(
        cellText=summary.values,
        colLabels=summary.columns,
        cellLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.3, 1.8)

    for (row, _col), cell in table.get_celld().items():
        cell.set_edgecolor(LIGHT)
        cell.set_linewidth(0.8)
        if row == 0:
            cell.set_facecolor(ACCENT)
            cell.set_text_props(color="white", weight="bold")
        else:
            cell.set_facecolor("white" if bg == "white" else BG)
            cell.set_text_props(color=DARK)

    ax.set_title(
        f"Browser Tracker Comparison\n{country}",
        fontsize=15,
        fontweight="bold",
        color=DARK,
        pad=20,
    )
    plt.tight_layout()
    return fig


def main():
    parser = argparse.ArgumentParser(description="Browser tracker comparison table")
    parser.add_argument("--data", default=os.path.join(ROOT, "cookies_data"))
    parser.add_argument(
        "--country",
        default="Netherlands",
        help="Country to compare browsers within (default: Netherlands)",
    )
    parser.add_argument(
        "--out", default=os.path.join(ROOT, "plots", "browser_comparison")
    )
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    ds = dataset(args.data)
    cookies = filter_country_browser(ds.classified_cookies, country=args.country)
    print(f"Country={args.country} Rows={len(cookies):,}")
    if cookies.empty:
        raise SystemExit(
            f"No cookies for country={args.country!r} "
            "(use --country all to include everything)."
        )
    print("Browsers found:", sorted(cookies["browser"].dropna().unique()))

    summary = build_summary(cookies)
    print("\nSummary:")
    print(summary)

    stem = f"browser_tracker_comparison_{args.country.replace(' ', '_')}"

    draw_table(summary, args.country, bg="cream")
    save_figure(args.out, f"{stem}.png", f"{stem}.pdf", facecolor=BG)

    draw_table(summary, args.country, bg="white")
    save_figure(args.out, f"{stem}_white.png", f"{stem}_white.pdf", facecolor="white")

    print("\nDone.")


if __name__ == "__main__":
    main()
