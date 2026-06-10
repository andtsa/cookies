"""
Top Third-Party Cookie Readers (by website coverage)

A horizontal bar chart of the reader domains (third-party scripts that called
``document.cookie``) ranked by the number of distinct first-party websites they
were observed reading cookies on — the empirical reach of each reader.

Reader rows come from the analysis engine
(:meth:`analysis.CookieDataset.third_party_reads`, cached by scripts/annotate.py);
``reader_domain`` is the registered domain of the first script in each read's JS
call-stack, first-party reads dropped.

Usage:
    python scripts/plot_scripts/plot_third_party_cookie_readers.py --data cookies_data --out plots/reads --top_n 20
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
    hbar_chart,
    annotate_hbars,
    gradient_colors,
    DARK,
)


def reader_coverage(data_dir: str) -> list[tuple[str, int]]:
    """Return ``[(reader_domain, distinct_site_count), ...]`` descending."""
    reader_sites: dict[str, set] = defaultdict(set)
    for row in dataset(data_dir).third_party_reads():
        reader = row.get("reader_domain")
        site = row.get("visited_domain")
        if reader and site:
            reader_sites[reader].add(site)
    pairs = [(r, len(sites)) for r, sites in reader_sites.items()]
    pairs.sort(key=lambda p: p[1], reverse=True)
    return pairs


def plot_top_readers(data_dir: str, out_dir: str, top_n: int = 20) -> None:
    apply_theme()
    pairs = reader_coverage(data_dir)

    fig, ax = plt.subplots(figsize=(10, 7))
    if not pairs:
        ax.text(
            0.5,
            0.5,
            "No third-party cookie reads found",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=14,
            color=DARK,
        )
        ax.axis("off")
        save_figure(out_dir, "top_reader_domains.png", "top_reader_domains.pdf")
        return

    top = pairs[:top_n]
    # Plot smallest-at-bottom: hbar_chart inverts so the largest sits on top.
    labels = [d for d, _ in top]
    values = [c for _, c in top]

    bars = hbar_chart(ax, labels, values, colors=gradient_colors(values))
    annotate_hbars(ax, bars, [f"{v:,}" for v in values])
    ax.set_title(f"Top {len(top)} Third-Party Cookie Readers by Website Coverage")
    ax.set_xlabel("Distinct websites where the reader read cookies")
    ax.set_ylabel("Reader domain")
    ax.grid(axis="x", alpha=0.3)
    plt.tight_layout()
    save_figure(out_dir, "top_reader_domains.png", "top_reader_domains.pdf")


if __name__ == "__main__":
    parser = make_parser(__doc__, data="./cookies_data", out="./plots/reads")
    parser.add_argument("--top_n", type=int, default=20)
    args = parser.parse_args()
    plot_top_readers(args.data, args.out, args.top_n)
