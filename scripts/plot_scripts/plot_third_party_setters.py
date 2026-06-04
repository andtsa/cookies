"""
Top Third-Party Cookie Setters
Ranks third-party domains by the number of distinct first-party sites on which they
set cookies. Reveals the "invisible hand" of ad-tech infrastructure.

Usage:
    python scripts/plot_scripts/plot_third_party_setters.py --data cookies_data --out plots/third_party
"""

import os
import sys
from collections import defaultdict

import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    dataset,
    save_figure,
    make_parser,
    gradient_colors,
    hbar_chart,
    annotate_hbars,
    clean_ax,
    MID,
)


def plot_setters(data_dir: str, out_dir: str, top_n: int = 25) -> None:
    apply_theme()
    df = dataset(data_dir).cookies
    tp = df[
        (df["set_by_third_party"] == True) & df["setter_domain"].notna()
    ]  # noqa: E712

    setter_sites: dict[str, set[str]] = defaultdict(set)
    for setter, site in zip(tp["setter_domain"], tp["registered_domain"]):
        if setter and setter != site:
            setter_sites[setter].add(site)

    if not setter_sites:
        print("No third-party cookie-setting data found.")
        return

    ranked = sorted(setter_sites.items(), key=lambda kv: len(kv[1]), reverse=True)[
        :top_n
    ]
    labels = [d for d, _ in ranked]
    counts = [len(s) for _, s in ranked]

    fig, ax = plt.subplots(figsize=(11, max(7, top_n * 0.42)))
    bars = hbar_chart(ax, labels, counts, colors=gradient_colors(counts))
    annotate_hbars(ax, bars, [f"{c:,} sites" for c in counts])
    ax.set_xlim(0, max(counts) * 1.18)
    ax.set_xlabel("Number of Distinct Sites Where Cookies Were Set", fontsize=13)
    ax.set_title(f"Top {top_n} Third-Party Cookie Setters", fontsize=16, pad=15)
    clean_ax(ax)
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
    save_figure(out_dir, "plot_third_party_setters.png")


if __name__ == "__main__":
    p = make_parser(out="./plots/third_party")
    p.add_argument("--top_n", default=25, type=int)
    args = p.parse_args()
    plot_setters(args.data, args.out, args.top_n)
