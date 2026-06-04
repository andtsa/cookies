"""
Top Sites by Share of Long-Lived Cookies
Ranks websites by the percentage of persistent cookies lasting longer than 1 year.

Usage:
    python scripts/plot_scripts/plot_longterm_offenders.py --data cookies_data --out plots/cookie_lifetime --top_n 25
"""

import os
import sys

import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    load_cookie_data,
    save_figure,
    make_parser,
    gradient_colors,
    hbar_chart,
    annotate_hbars,
    clean_ax,
    LIGHT,
)

LONGTERM_THRESHOLD_DAYS = 365


def plot_offenders(data_dir: str, out_dir: str, top_n: int = 25) -> None:
    apply_theme()
    _, cookies_df = load_cookie_data(data_dir)
    persistent = cookies_df[cookies_df["cookie_type"] == "persistent"].copy()
    persistent["long_lived"] = persistent["lifetime_days"] > LONGTERM_THRESHOLD_DAYS
    stats = (
        persistent.groupby("domain")
        .agg(total=("name", "count"), long_lived=("long_lived", "sum"))
        .reset_index()
    )
    stats = stats[stats["total"] >= 2]
    stats["pct_long"] = stats["long_lived"] / stats["total"] * 100
    top = stats.sort_values(["pct_long", "long_lived"], ascending=False).head(top_n)

    labels = top["domain"].str.replace(r"https?://", "", regex=True).str.rstrip("/")
    fig, ax = plt.subplots(figsize=(11, max(7, top_n * 0.42)))
    bars = hbar_chart(
        ax, labels, top["pct_long"], colors=gradient_colors(top["pct_long"])
    )
    annotate_hbars(
        ax,
        bars,
        [
            f"{p:.0f}%  ({c:.0f} cookies)"
            for p, c in zip(top["pct_long"], top["long_lived"])
        ],
        offset=0.8,
        fontsize=12,
    )
    ax.set_xlim(0, 115)
    ax.axvline(100, color=LIGHT, linewidth=0.8, linestyle=":")
    ax.set_xlabel(
        f"% of Persistent Cookies Lasting > {LONGTERM_THRESHOLD_DAYS} Days", fontsize=14
    )
    ax.set_title(
        f"Top {top_n} Websites by Share of Long-Lived Cookies", fontsize=16, pad=15
    )
    clean_ax(ax)
    ax.tick_params(axis="both", labelsize=12)
    save_figure(out_dir, "plot_longterm_offenders.png")


if __name__ == "__main__":
    p = make_parser(out="./plots/cookie_lifetime")
    p.add_argument("--top_n", default=25, type=int)
    args = p.parse_args()
    plot_offenders(args.data, args.out, args.top_n)
