"""
EasyPrivacy Blocking vs. Tracker Cookies

Cross-tabulates set_by.easyprivacy.matched against is_tracker to show:
- What fraction of tracker cookies were set by EasyPrivacy-matched requests?
- What fraction of EP-matched requests set tracker vs. non-tracker cookies?

Helps evaluate how well EasyPrivacy's request blocking actually stops
tracker cookie delivery.

Usage:
    python scripts/plot_scripts/plot_ep_effectiveness.py --data cookies_data --out plots/trackers
"""

import argparse
import os
import sys

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    load_cookie_data,
    save_figure,
    BG,
    DARK,
    MID,
    LIGHT,
    ACCENT,
    ACCENT2,
    COLORS,
)


def _to_bool_tracker(val) -> bool:
    if val is None or val is False:
        return False
    return bool(val) if isinstance(val, bool) else bool((val or {}).get("lists"))


def plot_ep_effectiveness(data_dir: str, out_dir: str) -> None:
    apply_theme()
    _, cookies_df = load_cookie_data(data_dir)

    if "is_tracker" not in cookies_df.columns:
        print("No is_tracker column; re-collect with --tracker-lists.")
        return

    df = cookies_df[cookies_df["set_by_ep_matched"].notna()].copy()
    if df.empty:
        print("No EasyPrivacy data in set_by field.")
        return

    df["is_tracker_bool"] = df["is_tracker"].apply(_to_bool_tracker)
    df["ep"] = df["set_by_ep_matched"].astype(bool)

    # 2×2 counts
    ep_tracker = (df["ep"] & df["is_tracker_bool"]).sum()
    ep_clean = (df["ep"] & ~df["is_tracker_bool"]).sum()
    nep_tracker = (~df["ep"] & df["is_tracker_bool"]).sum()
    nep_clean = (~df["ep"] & ~df["is_tracker_bool"]).sum()

    fig, axes = plt.subplots(1, 2, figsize=(13, 6))

    # ── Left: "Of EP-matched requests, how many set tracker vs. clean cookies?" ──
    ax = axes[0]
    ep_total = ep_tracker + ep_clean
    if ep_total:
        vals = [ep_tracker / ep_total * 100, ep_clean / ep_total * 100]
        labels = [f"Tracker\n{ep_tracker:,}", f"Non-Tracker\n{ep_clean:,}"]
        colors = [ACCENT, COLORS[2]]
        wedges, _ = ax.pie(
            vals, colors=colors, startangle=90,
            wedgeprops={"width": 0.5, "edgecolor": BG, "linewidth": 2},
        )
        for i, wedge in enumerate(wedges):
            angle = (wedge.theta2 + wedge.theta1) / 2
            x = 1.25 * np.cos(np.deg2rad(angle))
            y = 1.25 * np.sin(np.deg2rad(angle))
            ax.annotate(
                f"{labels[i]}\n({vals[i]:.1f}%)",
                xy=(0.9 * np.cos(np.deg2rad(angle)), 0.9 * np.sin(np.deg2rad(angle))),
                xytext=(x, y), ha="center", va="center", fontsize=10,
                fontweight="bold", color=DARK,
                arrowprops=dict(arrowstyle="-", color=DARK, lw=1.1),
            )
        ax.set_title(
            f"Cookies Set by EP-Matched Requests\n(n = {ep_total:,})",
            fontsize=13, pad=20,
        )
    else:
        ax.text(0.5, 0.5, "No EP-matched\nrequests found", ha="center", va="center",
                transform=ax.transAxes, fontsize=13, color=MID)

    # ── Right: "Of tracker cookies, how many came from EP-matched requests?" ──
    ax2 = axes[1]
    tracker_total = ep_tracker + nep_tracker
    if tracker_total:
        vals2 = [ep_tracker / tracker_total * 100, nep_tracker / tracker_total * 100]
        labels2 = [f"Set by EP\nmatched request\n{ep_tracker:,}",
                   f"Set by\nunmatched request\n{nep_tracker:,}"]
        colors2 = [ACCENT, ACCENT2]
        wedges2, _ = ax2.pie(
            vals2, colors=colors2, startangle=90,
            wedgeprops={"width": 0.5, "edgecolor": BG, "linewidth": 2},
        )
        for i, wedge in enumerate(wedges2):
            angle = (wedge.theta2 + wedge.theta1) / 2
            x = 1.28 * np.cos(np.deg2rad(angle))
            y = 1.28 * np.sin(np.deg2rad(angle))
            ax2.annotate(
                f"{labels2[i]}\n({vals2[i]:.1f}%)",
                xy=(0.9 * np.cos(np.deg2rad(angle)), 0.9 * np.sin(np.deg2rad(angle))),
                xytext=(x, y), ha="center", va="center", fontsize=10,
                fontweight="bold", color=DARK,
                arrowprops=dict(arrowstyle="-", color=DARK, lw=1.1),
            )
        ax2.set_title(
            f"Tracker Cookies by Request Source\n(n = {tracker_total:,} tracker cookies)",
            fontsize=13, pad=20,
        )
    else:
        ax2.text(0.5, 0.5, "No tracker cookies\nfound", ha="center", va="center",
                 transform=ax2.transAxes, fontsize=13, color=MID)

    fig.suptitle("EasyPrivacy Request Blocking vs. Tracker Cookies", fontsize=15, y=1.02)
    plt.tight_layout()
    save_figure(out_dir, "plot_ep_effectiveness.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--out", default="./plots/trackers")
    args = parser.parse_args()
    plot_ep_effectiveness(args.data, args.out)
