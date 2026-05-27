"""
Plot 5 — Cookie Security Flag Analysis
Grouped bar showing what % of persistent cookies have Secure, HttpOnly,
and SameSite flags — split by lifetime tier. Shows that long-lived
cookies often have weaker security settings — strong privacy finding.

Usage:
    python scripts/plot_scripts/plot_security_flags.py --data cookies_data --out plots/cookie_lifetime
"""

import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import os, sys

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    load_cookie_data,
    lifetime_bucket,
    save_figure,
    BUCKETS,
    BG,
    DARK,
    MID,
    LIGHT,
    COLORS,
)


def plot_security(data_dir: str, out_dir: str):
    apply_theme()
    _, cookies_df = load_cookie_data(data_dir)

    persistent = cookies_df[cookies_df["cookie_type"] == "persistent"].copy()
    persistent["bucket"] = persistent.apply(
        lambda r: lifetime_bucket(r["lifetime_days"], r["session"]), axis=1
    )
    # Drop session bucket (not relevant here)
    persistent = persistent[persistent["bucket"] != "Session"]

    flags = ["secure", "httpOnly"]
    buckets = [b for b in BUCKETS if b != "Session"]

    flag_labels = {"secure": "Secure flag", "httpOnly": "HttpOnly flag"}
    flag_colors = {"secure": COLORS[0], "httpOnly": COLORS[2]}

    # Also add SameSite set (not None/null)
    persistent["samesite_set"] = persistent["sameSite"].notna() & (
        persistent["sameSite"] != "None"
    )
    flags.append("samesite_set")
    flag_labels["samesite_set"] = "SameSite set"
    flag_colors["samesite_set"] = COLORS[4]

    # % of cookies in each bucket with each flag
    results = {}
    for flag in flags:
        pcts = []
        for bucket in buckets:
            sub = persistent[persistent["bucket"] == bucket]
            pcts.append(sub[flag].mean() * 100 if len(sub) else 0)
        results[flag] = pcts

    x = np.arange(len(buckets))
    width = 0.26
    offsets = [-width, 0, width]

    fig, ax = plt.subplots(figsize=(11, 5.5))

    for i, (flag, offset) in enumerate(zip(flags, offsets)):
        bars = ax.bar(
            x + offset,
            results[flag],
            width,
            color=flag_colors[flag],
            label=flag_labels[flag],
            edgecolor=BG,
            linewidth=0.7,
            alpha=0.9,
        )
        for bar in bars:
            h = bar.get_height()
            if h > 5:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    h + 0.8,
                    f"{h:.0f}%",
                    ha="center",
                    fontsize=7.5,
                    color=DARK,
                )

    ax.set_xticks(x)
    ax.set_xticklabels(buckets, rotation=15, ha="right")
    ax.set_ylim(0, 110)
    ax.set_ylabel("% of Cookies with Flag Set")
    ax.set_title("Security Flag Coverage by Cookie Lifetime Tier")
    ax.legend(fontsize=9)
    ax.grid(axis="y", alpha=0.35)
    ax.spines[["top", "right"]].set_visible(False)

    n = len(persistent)
    ax.text(
        0.01,
        -0.16,
        f"n = {n:,} persistent cookies across all sites",
        transform=ax.transAxes,
        fontsize=8.5,
        color=MID,
    )

    plt.tight_layout()
    save_figure(out_dir, "plot_security_flags.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookie_data")
    parser.add_argument("--out", default="./plots")
    args = parser.parse_args()
    plot_security(args.data, args.out)
