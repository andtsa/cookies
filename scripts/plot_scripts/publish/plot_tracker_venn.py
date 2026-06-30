"""
Venn diagram: trackers flagged by our signals vs. open-source blocklists

Two-circle Venn comparing cookies classified as probable or confirmed trackers:
  - Left:   flagged by our signals (behavioural / statistical / combined)
  - Right:  flagged by open-source lists (EasyPrivacy + OpenCookieDB)
  - Centre: flagged by both

Usage:
    python scripts/plot_scripts/plot_tracker_venn.py
    python scripts/plot_scripts/plot_tracker_venn.py \
        --data cookies_data --country Netherlands --browser chromium \
        --out plots/evidence
"""

import argparse
import os
import sys

import matplotlib.pyplot as plt
from matplotlib_venn import venn2, venn2_circles

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils import (
    apply_theme,
    dataset,
    save_figure,
    BG,
    DARK,
    LIGHT,
    ACCENT,
    ACCENT2,
    MID,
)


def _compute_sets(cc):
    """Split probable/confirmed trackers into: our signals only / lists only / both."""
    prob_plus = cc["tracker_tier"].isin(["confirmed", "probable"])
    sub = cc[prob_plus]

    has_list = sub["tracker_signals"].apply(
        lambda sigs: any(s.startswith("list:") for s in sigs)
    )
    has_ours = sub["tracker_signals"].apply(
        lambda sigs: any(not s.startswith("list:") for s in sigs)
    )

    return {
        "ours_only": int((has_ours & ~has_list).sum()),
        "lists_only": int((has_list & ~has_ours).sum()),
        "both": int((has_ours & has_list).sum()),
        "n_ours": int(has_ours.sum()),
        "n_lists": int(has_list.sum()),
        "n_total": len(sub),
    }


def plot_tracker_venn(
    data_dir: str, country: str | None, browser: str | None, out_dir: str
) -> None:
    apply_theme()
    ds = dataset(data_dir)
    cc = ds.classified_cookies

    if country and browser:
        cc = cc[(cc["country"] == country) & (cc["browser"] == browser)]

    counts = _compute_sets(cc)
    n_ours_only = counts["ours_only"]
    n_lists_only = counts["lists_only"]
    n_both = counts["both"]
    n_ours = counts["n_ours"]
    n_lists = counts["n_lists"]
    n_total = counts["n_total"]

    scope = f"{country} / {browser}" if country and browser else "all crawls"
    subsets = (n_ours_only, n_lists_only, n_both)

    fig, ax = plt.subplots(figsize=(9, 6))

    v = venn2(
        subsets=subsets,
        set_labels=("", ""),  # placed manually below
        set_colors=(ACCENT, MID),
        alpha=0.55,
        ax=ax,
    )

    # Crisp circle outlines — also gives us the Circle patches with center/radius
    circles = venn2_circles(subsets=subsets, linewidth=1.8, color=DARK, ax=ax)
    c_ours, c_lists = circles

    # Count labels inside "ours only" and "both"
    for rid, count, color in [
        ("10", n_ours_only, DARK),
        ("11", n_both, DARK),
    ]:
        lbl = v.get_label_by_id(rid)
        if lbl:
            lbl.set_text(f"{count:,}")
            lbl.set_fontsize(20)
            lbl.set_fontweight("bold")
            lbl.set_color(color)

    # "Lists only" slice: suppress the automatic label and draw a leader line instead
    lbl_01 = v.get_label_by_id("01")
    pos_01 = (
        lbl_01.get_position()
        if lbl_01
        else (c_lists.center[0] + c_lists.radius * 0.7, c_lists.center[1])
    )
    if lbl_01:
        lbl_01.set_text("")

    x_annot = c_lists.center[0] + c_lists.radius + 0.13
    ax.annotate(
        f"{n_lists_only:,}",
        xy=pos_01,
        xytext=(x_annot, pos_01[1]),
        fontsize=20,
        fontweight="bold",
        color=DARK,
        ha="left",
        va="center",
        arrowprops=dict(arrowstyle="-", color=DARK, lw=1.2),
    )

    # Set labels — placed on the outer sides, away from the centre
    ax.text(
        c_ours.center[0] - c_ours.radius - 0.06,
        c_ours.center[1],
        f"Our signals\n{n_ours:,} trackers",
        ha="right",
        va="center",
        fontsize=11,
        fontweight="bold",
        color=DARK,
    )
    ax.text(
        x_annot,
        c_lists.center[1] + c_lists.radius * 0.55,
        f"Open-source\nblocklists\n{n_lists:,} trackers",
        ha="left",
        va="center",
        fontsize=11,
        fontweight="bold",
        color=DARK,
    )

    ax.set_title(
        "Tracker detection: our signals vs. open-source blocklists",
        fontsize=14,
        fontweight="bold",
        color=DARK,
        pad=16,
    )
    fig.text(
        0.5,
        0.01,
        f"{n_total:,} cookies classified as probable or confirmed trackers  —  {scope}",
        ha="center",
        fontsize=10,
        color=DARK,
        style="italic",
    )

    plt.tight_layout(rect=[0, 0.04, 1, 1])
    slug = f"_{country.lower()}_{browser}" if country and browser else "_all"
    save_figure(out_dir, f"plot_tracker_venn{slug}.png", f"plot_tracker_venn{slug}.pdf")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--country", default="Netherlands")
    parser.add_argument("--browser", default="chromium")
    parser.add_argument("--out", default="./plots/evidence")
    args = parser.parse_args()
    plot_tracker_venn(args.data, args.country, args.browser, args.out)
