"""
Tracker Share by Cookie Lifetime Bucket
Grouped bar showing what % of cookies in each lifetime tier are trackers,
vs non-trackers. Shows whether long-lived cookies are more likely to track.
Mirrors the security-flags plot style.

Usage:
    python scripts/plot_scripts/plot_tracker_by_lifetime.py --data cookies_data --out plots/trackers
"""

import argparse
import json
import os
import sys
import glob

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme, lifetime_bucket,
    BUCKETS, BG, DARK, MID, LIGHT, COLORS, ACCENT, ACCENT2,
)


def load_tracker_cookies(data_dir: str) -> pd.DataFrame:
    rows = []
    paths = glob.glob(os.path.join(data_dir, "*.json"))
    if not paths:
        raise FileNotFoundError(f"No JSON files found in: {data_dir}")
    for path in paths:
        with open(path) as f:
            data = json.load(f)
        domain = os.path.basename(path).replace(".json", "")
        for cookie in data.get("cookies", []):
            if "is_tracker" not in cookie:
                continue
            tracker_val = cookie["is_tracker"]
            is_tracker = bool(tracker_val) if isinstance(tracker_val, bool) else bool(tracker_val.get("lists"))
            rows.append({
                "domain":        domain,
                "name":          cookie.get("name"),
                "is_tracker":    is_tracker,
                "session":       cookie.get("session", True),
                "lifetime_days": cookie.get("lifetime_days") or 0,
            })
    if not rows:
        raise ValueError(
            "No cookies with is_tracker found. "
            "Re-collect with --tracker-lists to annotate trackers."
        )
    return pd.DataFrame(rows)


def plot_tracker_by_lifetime(data_dir: str, out_dir: str) -> None:
    apply_theme()
    df = load_tracker_cookies(data_dir)

    df["bucket"] = df.apply(
        lambda r: lifetime_bucket(r["lifetime_days"], r["session"]), axis=1
    )

    # % tracker per bucket
    tracker_pcts  = []
    bucket_counts = []
    for bucket in BUCKETS:
        sub = df[df["bucket"] == bucket]
        n   = len(sub)
        bucket_counts.append(n)
        tracker_pcts.append(sub["is_tracker"].mean() * 100 if n else 0)

    x      = np.arange(len(BUCKETS))
    width  = 0.38

    tracker_color     = ACCENT          # orange
    nontracker_color  = COLORS[2]       # muted purple from palette

    fig, ax = plt.subplots(figsize=(12, 5.5))

    bars_t = ax.bar(
        x - width / 2, tracker_pcts,
        width, label="Tracker",
        color=tracker_color, edgecolor=BG, linewidth=0.7, alpha=0.9,
    )
    bars_nt = ax.bar(
        x + width / 2, [100 - p for p in tracker_pcts],
        width, label="Non-Tracker",
        color=nontracker_color, edgecolor=BG, linewidth=0.7, alpha=0.9,
    )

    # Value labels on tracker bars
    for bar, pct in zip(bars_t, tracker_pcts):
        h = bar.get_height()
        if h > 3:
            ax.text(
                bar.get_x() + bar.get_width() / 2, h + 0.8,
                f"{h:.0f}%", ha="center", fontsize=7.5, color=DARK,
            )

    # Cookie count annotation below x-axis labels
    ax.set_xticks(x)
    ax.set_xticklabels(BUCKETS, rotation=15, ha="right")
    ax.set_ylim(0, 115)
    ax.set_ylabel("% of Cookies in Bucket")
    ax.set_title("Tracker Share by Cookie Lifetime Bucket")
    ax.legend(fontsize=9)
    ax.grid(axis="y", alpha=0.35)
    ax.spines[["top", "right"]].set_visible(False)

    # Sample sizes as a footer line
    n_total = len(df)
    ax.text(
        0.01, -0.18,
        f"n = {n_total:,} annotated cookies across all sites  |  "
        + "  ".join(f"{b}: {c:,}" for b, c in zip(BUCKETS, bucket_counts)),
        transform=ax.transAxes, fontsize=7.5, color=MID,
    )

    plt.tight_layout()
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "plot_tracker_by_lifetime.png")
    plt.savefig(out_path, dpi=300, bbox_inches="tight", facecolor=BG)
    print(f"Saved → {out_path}")
    plt.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--out",  default="./plots/trackers")
    args = parser.parse_args()
    plot_tracker_by_lifetime(args.data, args.out)