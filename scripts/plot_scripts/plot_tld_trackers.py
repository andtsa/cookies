"""
Trackers vs. Lifetime by Top-Level Domain

For each TLD seen in the crawl: how many tracker cookies were set, and how
long do they persist (median lifetime of non-session tracker cookies)?
"""

import os
import sys

import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from utils import apply_theme, save_figure, dataset, ACCENT, ACCENT2, DARK


def main(data_dir: str = "cookies_data", out_dir: str = "plots/trackers_vs_lifetime", top_n: int = 12):
    ds = dataset(data_dir)

    # one row per TLD: how many tracker cookies were set there
    counts = ds.group(by=["tld"], trackers_only=True, metric="count")

    # one row per TLD: median lifetime of *persistent* tracker cookies
    # (`where` is pre-filter pushed through `_scan`; `trackers_only` ANDs in is_tracker)
    lifetimes = ds.group(
        by=["tld"],
        trackers_only=True,
        where={"session": False},
        metric="median:lifetime_days",
    )

    merged = (
        counts.merge(lifetimes, on="tld", suffixes=("_count", "_lifetime"))
        .sort_values("value_count", ascending=False)
        .head(top_n)
    )

    apply_theme()
    fig, ax1 = plt.subplots(figsize=(11, 6))

    ax1.bar(merged["tld"], merged["value_count"], color=ACCENT, label="# tracker cookies")
    ax1.set_ylabel("# tracker cookies", color=ACCENT)
    ax1.set_xlabel("Top-level domain")
    ax1.tick_params(axis="x", rotation=45)

    ax2 = ax1.twinx()
    ax2.plot(
        merged["tld"], merged["value_lifetime"],
        color=ACCENT2, marker="o", linewidth=2, label="median lifetime (days)",
    )
    ax2.set_ylabel("median lifetime, days (persistent only)", color=ACCENT2)
    ax2.grid(False)

    ax1.set_title("Tracker prevalence vs. lifetime, by top-level domain", color=DARK)
    fig.tight_layout()
    save_figure(out_dir, "trackers_vs_lifetime_by_tld.png")


if __name__ == "__main__":
    data = sys.argv[1] or "cookies_data"
    main(data)
