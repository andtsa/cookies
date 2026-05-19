"""
Plot 4 — Top Sites by Share of Long-Lived Cookies
Ranks websites by the percentage of persistent cookies
lasting longer than 1 year.

Usage:
    python scripts/plot_scripts/plot_longterm_offenders.py --data cookies_data --out plots/cookie_lifetime --top_n 25
"""

import argparse
import matplotlib.pyplot as plt
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from utils import apply_theme, load_cookie_data, BG, DARK, MID, LIGHT

LONGTERM_THRESHOLD_DAYS = 365


def plot_offenders(data_dir: str, out_dir: str, top_n: int = 25):
    apply_theme()
    _, cookies_df = load_cookie_data(data_dir)

    # Keep only persistent cookies
    persistent = cookies_df[cookies_df["cookie_type"] == "persistent"].copy()
    persistent["long_lived"] = persistent["lifetime_days"] > LONGTERM_THRESHOLD_DAYS

    # Aggregate per domain
    stats = (
        persistent.groupby("domain")
        .agg(total=("name", "count"), long_lived=("long_lived", "sum"))
        .reset_index()
    )

    # Filter tiny samples
    stats = stats[stats["total"] >= 2]

    stats["pct_long"] = stats["long_lived"] / stats["total"] * 100

    # Top N sorted descending
    top = stats.sort_values(["pct_long", "long_lived"], ascending=[False, False]).head(
        top_n
    )

    # Create gradient colors manually
    norm = plt.Normalize(top["pct_long"].min(), top["pct_long"].max())

    colors = [
        plt.matplotlib.colors.to_hex(
            plt.matplotlib.colors.hsv_to_rgb(
                [
                    0.06,  # orange hue
                    0.4 + 0.55 * norm(v),
                    0.9 - 0.35 * norm(v),
                ]
            )
        )
        for v in top["pct_long"]
    ]

    labels = top["domain"].str.replace(r"https?://", "", regex=True).str.rstrip("/")

    fig, ax = plt.subplots(figsize=(11, max(7, top_n * 0.42)))

    bars = ax.barh(
        labels, top["pct_long"], color=colors, edgecolor=BG, linewidth=0.6, height=0.72
    )

    # Put highest at top
    ax.invert_yaxis()
    ax.tick_params(axis="both", labelsize=12)

    # Labels on bars
    for bar, pct, count in zip(bars, top["pct_long"], top["long_lived"]):
        ax.text(
            bar.get_width() + 0.8,
            bar.get_y() + bar.get_height() / 2,
            f"{pct:.0f}%  ({count:.0f} cookies)",
            va="center",
            fontsize=12,
            color=DARK,
        )

    ax.set_xlim(0, 115)

    ax.axvline(100, color=LIGHT, linewidth=0.8, linestyle=":")

    ax.set_xlabel(
        f"% of Persistent Cookies Lasting > {LONGTERM_THRESHOLD_DAYS} Days", fontsize=14
    )

    ax.set_title(
        f"Top {top_n} Websites by Share of Long-Lived Cookies", fontsize=16, pad=15
    )

    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", alpha=0.3)

    plt.tight_layout()

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "plot_longterm_offenders.png")

    plt.savefig(out_path, dpi=300, bbox_inches="tight", facecolor=BG)

    print(f"Saved → {out_path}")
    plt.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookie_data")
    parser.add_argument("--out", default="./plots")
    parser.add_argument("--top_n", default=25, type=int)

    args = parser.parse_args()
    plot_offenders(args.data, args.out, args.top_n)
