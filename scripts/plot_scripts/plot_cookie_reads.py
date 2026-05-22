"""
JS Cookie Read Analysis

Analyses the cookie_reads data embedded in each site JSON to understand:
1. How many unique cookie names are JS-read per page?
2. Which cookie names are read most frequently across all sites?

Requires data collected with --intercept-cookie-reads enabled.

Usage:
    python scripts/plot_scripts/plot_cookie_reads.py --data cookies_data --out plots/cookie_reads
"""

import argparse
import os
import sys
from collections import Counter, defaultdict

import matplotlib.pyplot as plt
import numpy as np

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


def load_read_data(data_dir: str):
    """
    Returns:
        reads_per_site: list of unique-cookie-name counts per site
        name_counter:   Counter of how many distinct sites each name is read on
    """
    reads_per_site = []
    name_sites: dict[str, set[str]] = defaultdict(set)

    for domain, browser, data in _iter_cookie_files(data_dir):
        cookie_reads = data.get("cookie_reads")
        if not cookie_reads or not cookie_reads.get("reads"):
            continue

        visited = cookie_reads.get("visited_domain", domain)
        names_this_site: set[str] = set()

        for read_event in cookie_reads["reads"]:
            raw = read_event.get("cookies", "")
            for part in raw.split(";"):
                part = part.strip()
                if not part:
                    continue
                name = part.split("=", 1)[0].strip()
                if name:
                    names_this_site.add(name)

        reads_per_site.append(len(names_this_site))
        for name in names_this_site:
            name_sites[name].add(visited)

    name_counter = Counter({name: len(sites) for name, sites in name_sites.items()})
    return reads_per_site, name_counter


def plot_cookie_reads(data_dir: str, out_dir: str, top_n: int = 20) -> None:
    apply_theme()

    reads_per_site, name_counter = load_read_data(data_dir)

    if not reads_per_site:
        print(
            "No cookie_reads data found. "
            "Re-collect with --intercept-cookie-reads enabled."
        )
        return

    fig, (ax_hist, ax_bar) = plt.subplots(1, 2, figsize=(14, 6))

    # ── Left: distribution of unique cookies read per site ────────────────
    data_arr = np.array(reads_per_site)
    bins = np.arange(0, data_arr.max() + 2) - 0.5
    ax_hist.hist(data_arr, bins=bins, color=ACCENT, edgecolor=BG, linewidth=0.6, alpha=0.9)
    ax_hist.axvline(np.median(data_arr), color=ACCENT2, linewidth=1.8, linestyle="--",
                    label=f"Median: {np.median(data_arr):.0f}")
    ax_hist.axvline(np.mean(data_arr), color=COLORS[4], linewidth=1.8, linestyle=":",
                    label=f"Mean: {np.mean(data_arr):.1f}")
    ax_hist.set_xlabel("Unique Cookie Names JS-Read per Site")
    ax_hist.set_ylabel("Number of Sites")
    ax_hist.set_title("JS Cookie Reads per Site")
    ax_hist.legend(fontsize=10)
    ax_hist.grid(axis="y", alpha=0.35)
    ax_hist.spines[["top", "right"]].set_visible(False)
    ax_hist.text(
        0.98, 0.97,
        f"n = {len(reads_per_site):,} sites",
        transform=ax_hist.transAxes, ha="right", va="top", fontsize=9, color=MID,
    )

    # ── Right: top cookie names by number of sites where they were read ───
    top = name_counter.most_common(top_n)
    if top:
        names, site_counts = zip(*top)
        y = np.arange(len(names))
        norm = plt.Normalize(min(site_counts), max(site_counts))
        colors = [
            plt.matplotlib.colors.to_hex(
                plt.matplotlib.colors.hsv_to_rgb(
                    [0.06, 0.35 + 0.6 * norm(c), 0.9 - 0.3 * norm(c)]
                )
            )
            for c in site_counts
        ]
        bars = ax_bar.barh(y, site_counts, color=colors, edgecolor=BG,
                           linewidth=0.6, height=0.72)
        ax_bar.set_yticks(y)
        ax_bar.set_yticklabels(names, fontsize=10)
        ax_bar.invert_yaxis()
        for bar, count in zip(bars, site_counts):
            ax_bar.text(
                bar.get_width() + max(site_counts) * 0.01,
                bar.get_y() + bar.get_height() / 2,
                f"{count:,}",
                va="center", fontsize=9, color=DARK,
            )
        ax_bar.set_xlabel("Number of Distinct Sites Where Cookie Was JS-Read")
        ax_bar.set_title(f"Top {top_n} Most-Read Cookie Names")
        ax_bar.grid(axis="x", alpha=0.3)
        ax_bar.spines[["top", "right"]].set_visible(False)
        ax_bar.set_xlim(0, max(site_counts) * 1.15)

    plt.tight_layout()
    save_figure(out_dir, "plot_cookie_reads.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--out", default="./plots/cookie_reads")
    parser.add_argument("--top_n", default=20, type=int)
    args = parser.parse_args()
    plot_cookie_reads(args.data, args.out, args.top_n)
