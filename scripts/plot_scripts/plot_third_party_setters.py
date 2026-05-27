"""
Top Third-Party Cookie Setters

Ranks third-party domains by the number of distinct first-party sites on which
they set cookies via cross-origin requests (set_by.third_party == true).
Reveals the "invisible hand" of ad-tech infrastructure.

Usage:
    python scripts/plot_scripts/plot_third_party_setters.py --data cookies_data --out plots/third_party
"""

import argparse
import os
import sys
from collections import defaultdict
from urllib.parse import urlparse

import matplotlib.pyplot as plt
import tldextract

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    _iter_cookie_files,
    save_figure,
    BG,
    DARK,
    LIGHT,
    ACCENT,
    MID,
)


def load_third_party_setters(data_dir: str) -> dict[str, set[str]]:
    """
    Return {setter_domain -> {first_party_site, ...}} using set_by.third_party.
    Only cookies whose set_by.third_party is True are counted.
    """
    setter_sites: dict[str, set[str]] = defaultdict(set)

    for domain, browser, data in _iter_cookie_files(data_dir):
        target_url = data.get("target_url", "")
        site_label = tldextract.extract(target_url).registered_domain or domain

        for cookie in data.get("cookies", []):
            set_by = cookie.get("set_by") or {}
            if not set_by.get("third_party"):
                continue
            setter_url = set_by.get("url", "")
            if not setter_url:
                continue
            setter_domain = tldextract.extract(setter_url).registered_domain
            if setter_domain and setter_domain != site_label:
                setter_sites[setter_domain].add(site_label)

    return dict(setter_sites)


def plot_setters(data_dir: str, out_dir: str, top_n: int = 25) -> None:
    apply_theme()

    setter_sites = load_third_party_setters(data_dir)
    if not setter_sites:
        print("No third-party cookie-setting data found (need set_by.third_party).")
        return

    # Sort by number of distinct sites
    ranked = sorted(setter_sites.items(), key=lambda kv: len(kv[1]), reverse=True)[
        :top_n
    ]
    labels = [d for d, _ in ranked]
    counts = [len(s) for _, s in ranked]

    norm = plt.Normalize(min(counts), max(counts))
    colors = [
        plt.matplotlib.colors.to_hex(
            plt.matplotlib.colors.hsv_to_rgb(
                [0.06, 0.35 + 0.6 * norm(c), 0.9 - 0.3 * norm(c)]
            )
        )
        for c in counts
    ]

    fig, ax = plt.subplots(figsize=(11, max(7, top_n * 0.42)))
    bars = ax.barh(
        labels, counts, color=colors, edgecolor=BG, linewidth=0.6, height=0.72
    )
    ax.invert_yaxis()

    for bar, count in zip(bars, counts):
        ax.text(
            bar.get_width() + 0.3,
            bar.get_y() + bar.get_height() / 2,
            f"{count:,} sites",
            va="center",
            fontsize=11,
            color=DARK,
        )

    ax.set_xlabel("Number of Distinct Sites Where Cookies Were Set", fontsize=13)
    ax.set_title(f"Top {top_n} Third-Party Cookie Setters", fontsize=16, pad=15)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", alpha=0.3)
    ax.set_xlim(0, max(counts) * 1.18)

    total_sites = len({s for _, sites in ranked for s in sites})
    ax.text(
        0.99,
        0.02,
        f"Based on {len(setter_sites):,} unique third-party setters across {total_sites:,} sites",
        transform=ax.transAxes,
        ha="right",
        fontsize=8.5,
        color=MID,
    )

    plt.tight_layout()
    save_figure(out_dir, "plot_third_party_setters.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--out", default="./plots/third_party")
    parser.add_argument("--top_n", default=25, type=int)
    args = parser.parse_args()
    plot_setters(args.data, args.out, args.top_n)
