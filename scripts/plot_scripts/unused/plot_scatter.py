"""
Plot 3 — Tracking Burden by Top-Level Domain
One point = one TLD (.com, .org, .net, etc.)

Usage:
    python scripts/plot_scripts/plot_scatter.py --data cookies_data --out plots/cookie_lifetime
"""

import argparse
import matplotlib.pyplot as plt
import os
import re
import sys
from adjustText import adjust_text

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    load_cookie_data,
    save_figure,
    ACCENT,
    ACCENT2,
    DARK,
    MID,
    LIGHT,
)


def extract_tld(domain: str) -> str:
    match = re.search(r"\.([a-zA-Z]{2,})$", domain)
    if match:
        return "." + match.group(1).lower()
    return ".other"


def plot_scatter(data_dir: str, out_dir: str):
    apply_theme()
    _, cookies_df = load_cookie_data(data_dir)

    cookies_df["tld"] = cookies_df["domain"].apply(extract_tld)

    # Aggregate cookie counts per TLD
    cookie_stats = (
        cookies_df.groupby(["tld", "domain"])
        .agg(site_cookie_count=("name", "count"))
        .reset_index()
        .groupby("tld")
        .agg(avg_total_cookies=("site_cookie_count", "mean"))
        .reset_index()
    )

    # Persistent cookie lifetime stats
    persistent = cookies_df[cookies_df["cookie_type"] == "persistent"].copy()

    lifetime_stats = (
        persistent.groupby("tld")
        .agg(
            median_lifetime_days=("lifetime_days", "median"),
            num_persistent=("name", "count"),
        )
        .reset_index()
    )

    df = cookie_stats.merge(lifetime_stats, on="tld")

    # axes
    x = df["median_lifetime_days"]
    y = df["avg_total_cookies"]

    x_mid = x.median()
    y_mid = y.median()

    fig, ax = plt.subplots(figsize=(10, 7))

    xmax = x.max() * 1.18
    ymax = y.max() * 1.18

    # Quadrant shading
    ax.axvspan(x_mid, xmax, ymin=y_mid / ymax, ymax=1, color=ACCENT, alpha=0.2)

    ax.axvspan(x_mid, xmax, ymin=0, ymax=y_mid / ymax, color=ACCENT, alpha=0.08)

    ax.axvline(x_mid, color=LIGHT, linewidth=1.2, linestyle="--")

    ax.axhline(y_mid, color=LIGHT, linewidth=1.2, linestyle="--")

    sizes = 10

    ax.scatter(x, y, s=sizes, color=MID, alpha=0.65, edgecolors=DARK, linewidths=0.5)

    texts = []

    for _, row in df.iterrows():
        text = ax.text(
            row["median_lifetime_days"],
            row["avg_total_cookies"],
            row["tld"],
            fontsize=10,
            color=DARK,
        )
        texts.append(text)

    adjust_text(
        texts, ax=ax, arrowprops=dict(arrowstyle="-", color=DARK, lw=1.0, alpha=0.7)
    )

    # Quadrant labels
    ax.text(
        xmax * 0.997,
        ymax * 0.997,
        "HIGH COOKIE COUNT\nLONG LIFETIME",
        fontsize=8,
        color=ACCENT,
        fontweight="bold",
        ha="right",
        va="top",
    )

    ax.text(
        xmax * 0.997,
        y_mid * 0.79,
        "LOW COOKIE COUNT\nLONG LIFETIME",
        fontweight="bold",
        fontsize=7.5,
        color=MID,
        ha="right",
    )

    ax.text(
        x_mid * 0.003,
        ymax * 0.997,
        "HIGH COOKIE COUNT\nSHORT LIFETIME",
        fontweight="bold",
        fontsize=7.5,
        color=MID,
        va="top",
    )

    ax.text(
        x_mid * 0.003,
        y_mid * 0.79,
        "LOW COOKIE COUNT\nSHORT LIFETIME",
        fontweight="bold",
        fontsize=7.5,
        color=MID,
    )

    ax.set_xlim(left=-2, right=xmax)
    ax.set_ylim(bottom=0, top=ymax)

    ax.set_xlabel("Median Cookie Lifetime (Days)", fontsize=11)

    ax.set_ylabel("Average Cookies per Website", fontsize=11)

    ax.set_title(
        "Cookie Lifetime and Count Across 27 Top-Level Domains", fontsize=15, pad=14
    )

    ax.tick_params(axis="both", labelsize=10)

    ax.grid(alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)

    plt.tight_layout()
    save_figure(out_dir, "plot_scatter.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookie_data")
    parser.add_argument("--out", default="./plots")

    args = parser.parse_args()
    plot_scatter(args.data, args.out)
