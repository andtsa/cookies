"""
Cookie Initiator Attribution

Identifies which JS scripts (set_by.initiator) are responsible for triggering
the most third-party cookie-setting requests. Pinpoints the specific CDN-hosted
scripts (analytics.js, fbevents.js, etc.) behind cross-site tracking.

Usage:
    python scripts/plot_scripts/plot_cookie_initiators.py --data cookies_data --out plots/third_party
"""

import argparse
import os
import sys
from collections import Counter, defaultdict
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
    MID,
    LIGHT,
    ACCENT,
    COLORS,
)


def _script_label(initiator_url: str) -> str:
    """Return a short human-readable label for an initiator URL."""
    if not initiator_url:
        return "(direct / unknown)"
    parsed = urlparse(initiator_url)
    path = parsed.path.rstrip("/")
    filename = path.split("/")[-1] if path else ""
    domain = tldextract.extract(initiator_url).registered_domain or parsed.netloc
    if filename:
        return f"{domain}/{filename}"
    return domain


def load_initiator_data(data_dir: str, only_third_party: bool = True):
    """
    Returns:
        initiator_cookie_count: Counter of (initiator_label -> cookie count)
        initiator_site_count:   Counter of (initiator_label -> distinct sites)
    """
    cookie_counter: Counter = Counter()
    site_map: dict[str, set[str]] = defaultdict(set)

    for domain, browser, data in _iter_cookie_files(data_dir):
        for cookie in data.get("cookies", []):
            set_by = cookie.get("set_by") or {}
            if only_third_party and not set_by.get("third_party"):
                continue
            initiator = set_by.get("initiator", "")
            label = _script_label(initiator)
            cookie_counter[label] += 1
            site_map[label].add(domain)

    site_counter = Counter({label: len(sites) for label, sites in site_map.items()})
    return cookie_counter, site_counter


def plot_initiators(data_dir: str, out_dir: str, top_n: int = 20) -> None:
    apply_theme()

    cookie_counter, site_counter = load_initiator_data(data_dir)

    if not cookie_counter:
        print("No set_by.initiator data found.")
        return

    # Rank by number of distinct sites
    top = site_counter.most_common(top_n)
    labels = [label for label, _ in top]
    site_counts = [count for _, count in top]
    cookie_counts = [cookie_counter[label] for label in labels]

    import numpy as np
    y = np.arange(len(labels))

    norm = plt.Normalize(min(site_counts), max(site_counts))
    colors = [
        plt.matplotlib.colors.to_hex(
            plt.matplotlib.colors.hsv_to_rgb(
                [0.06, 0.35 + 0.6 * norm(c), 0.9 - 0.3 * norm(c)]
            )
        )
        for c in site_counts
    ]

    fig, (ax_sites, ax_cookies) = plt.subplots(1, 2, figsize=(16, max(7, top_n * 0.42)))

    # Left: by distinct sites
    bars = ax_sites.barh(y, site_counts, color=colors, edgecolor=BG,
                         linewidth=0.6, height=0.72)
    ax_sites.set_yticks(y)
    ax_sites.set_yticklabels(labels, fontsize=9)
    ax_sites.invert_yaxis()
    for bar, count in zip(bars, site_counts):
        ax_sites.text(
            bar.get_width() + max(site_counts) * 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"{count:,} sites",
            va="center", fontsize=9, color=DARK,
        )
    ax_sites.set_xlabel("Distinct Sites")
    ax_sites.set_title(f"Top {top_n} Initiator Scripts\n(by site reach)", fontsize=13, pad=12)
    ax_sites.grid(axis="x", alpha=0.3)
    ax_sites.spines[["top", "right"]].set_visible(False)
    ax_sites.set_xlim(0, max(site_counts) * 1.2)

    # Right: by total cookies set
    bars2 = ax_cookies.barh(y, cookie_counts, color=COLORS[2], edgecolor=BG,
                            linewidth=0.6, height=0.72)
    ax_cookies.set_yticks(y)
    ax_cookies.set_yticklabels(labels, fontsize=9)
    ax_cookies.invert_yaxis()
    for bar, count in zip(bars2, cookie_counts):
        ax_cookies.text(
            bar.get_width() + max(cookie_counts) * 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"{count:,}",
            va="center", fontsize=9, color=DARK,
        )
    ax_cookies.set_xlabel("Total Cookies Set")
    ax_cookies.set_title(f"Top {top_n} Initiator Scripts\n(by cookie volume)", fontsize=13, pad=12)
    ax_cookies.grid(axis="x", alpha=0.3)
    ax_cookies.spines[["top", "right"]].set_visible(False)
    ax_cookies.set_xlim(0, max(cookie_counts) * 1.2)

    fig.suptitle("Third-Party Cookie Initiator Scripts", fontsize=16, y=1.02)
    plt.tight_layout()
    save_figure(out_dir, "plot_cookie_initiators.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--out", default="./plots/third_party")
    parser.add_argument("--top_n", default=20, type=int)
    parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Include first-party cookies too (default: third-party only)",
    )
    args = parser.parse_args()
    plot_initiators(args.data, args.out, args.top_n)
