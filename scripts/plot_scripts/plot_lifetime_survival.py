"""
Plot — Lifetime survival curve: all persistent cookies vs persistent trackers

Usage:
    python scripts/plot_scripts/plot_lifetime_survival.py \
        --data ../../cookies_data \
        --out plots
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))

from utils import (
    dataset,
    apply_theme,
    save_figure,
    COLORS,
    BG,
)

THRESHOLDS = [
    (1, "1 day"),
    (7, "1 week"),
    (30, "1 month"),
    (90, "3 months"),
    (180, "6 months"),
    (365, "1 year"),
    (730, "2 years"),
    (1825, "5 years"),
]


def survival_curve(lifetime_days: pd.Series) -> list[float]:
    """
    For each threshold return the % of cookies with lifetime_days >= threshold.
    lifetime_days must already be filtered to persistent-only (non-null, > 0).
    """
    n = len(lifetime_days)
    if n == 0:
        return [0.0] * len(THRESHOLDS)
    return [round((lifetime_days >= days).sum() / n * 100, 1) for days, _ in THRESHOLDS]


def plot_lifetime_survival(data_dir: str, out_dir: str):
    apply_theme()

    ds = dataset(data_dir)

    # ── All persistent cookies ──
    cookies = ds.cookies
    persistent_all = cookies[
        (~cookies["session"])
        & (cookies["lifetime_days"].notna())
        & (cookies["lifetime_days"] > 0)
    ]["lifetime_days"]

    # ── Persistent trackers only ──
    classified = ds.classified_cookies
    persistent_trackers = classified[
        (classified["is_tracker"])
        & (~classified["session"])
        & (classified["lifetime_days"].notna())
        & (classified["lifetime_days"] > 0)
    ]["lifetime_days"]

    curve_all = survival_curve(persistent_all)
    curve_trackers = survival_curve(persistent_trackers)
    x_labels = [label for _, label in THRESHOLDS]
    x = np.arange(len(THRESHOLDS))

    def draw_and_save(curve, color, title, n, png, pdf):
        fig, ax = plt.subplots(figsize=(8, 5))

        ax.step(x, curve, where="post", color=color, linewidth=2.5)
        ax.fill_between(x, curve, step="post", color=color, alpha=0.08)
        ax.plot(x, curve, "o", color=color, markersize=5, zorder=3)

        for xi, val in zip(x, curve):
            ax.annotate(
                f"{val}%",
                xy=(xi, val),
                xytext=(0, 8),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=9,
                fontweight="bold",
                color=color,
            )

        ax.set_title(f"{title}\n(n={n:,} persistent cookies)", fontsize=12, pad=10)
        ax.set_xticks(x)
        ax.set_xticklabels(x_labels, rotation=30, ha="right", fontsize=10)
        ax.set_ylim(0, 110)
        ax.set_ylabel("% of cookies with lifetime ≥ threshold", fontsize=10)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
        ax.tick_params(axis="y", labelsize=10)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="y", color="#cccccc", linewidth=0.5, linestyle="--")

        plt.tight_layout()
        save_figure(out_dir, png, pdf)
        plt.close(fig)

    draw_and_save(
        curve_all,
        COLORS[0],
        "How long do persistent cookies last?",
        len(persistent_all),
        "lifetime_survival_all.png",
        "lifetime_survival_all.pdf",
    )
    draw_and_save(
        curve_trackers,
        COLORS[2],
        "How long do persistent tracker cookies last?",
        len(persistent_trackers),
        "lifetime_survival_trackers.png",
        "lifetime_survival_trackers.pdf",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="../../cookies_data")
    parser.add_argument("--out", default="plots")
    args = parser.parse_args()
    plot_lifetime_survival(args.data, args.out)
