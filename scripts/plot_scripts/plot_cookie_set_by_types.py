"""
Cookie Injection by Request Type

Shows the distribution of set_by.type values across all cookies that have
network context data (i.e. where the Set-Cookie response was observed).
Answers: "are tracking cookies set via invisible pixels (Image), AJAX calls
(XHR/Fetch), or inline scripts (Document/Script)?"

Also shows the tracker share per resource type as a stacked bar.

Usage:
    python scripts/plot_scripts/plot_cookie_set_by_type.py --data cookies_data --out plots/third_party
"""

import argparse
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    load_cookie_data,
    save_figure,
    BG,
    DARK,
    MID,
    COLORS,
    ACCENT,
)

# Preferred display order for known types; any unknown types are appended
# alphabetically after these rather than collapsed into a single "Other" bucket.
KNOWN_TYPE_ORDER = [
    "document",
    "xhr",
    "fetch",
    "script",
    "image",
    "stylesheet",
    "media",
    "font",
    "ping",
    "websocket",
]


def build_type_order(series) -> list[str]:
    """
    Return an ordered list of all type values present in *series*.

    Known types come first (in KNOWN_TYPE_ORDER sequence), followed by any
    unrecognised values sorted alphabetically.  Nothing is discarded.
    """
    present = set(series.dropna().str.lower().unique())
    known_present = [t for t in KNOWN_TYPE_ORDER if t in present]
    unknown_present = sorted(present - set(KNOWN_TYPE_ORDER))
    return known_present + unknown_present


def plot_set_by_type(data_dir: str, out_dir: str) -> None:
    apply_theme()
    _, cookies_df = load_cookie_data(data_dir)

    # Only cookies where we have network context
    ctx = cookies_df[cookies_df["set_by_type"].notna()].copy()
    ctx["set_by_type"] = ctx["set_by_type"].str.lower()
    if ctx.empty:
        print("No set_by_type data found. Collected with a browser that supports CDP?")
        return

    type_order = build_type_order(ctx["set_by_type"])
    n_types = len(type_order)

    counts = ctx["set_by_type"].value_counts().reindex(type_order, fill_value=0)
    total = counts.sum()
    pcts = counts / total * 100

    # Extend colour palette if there are more types than built-in colours
    palette = (COLORS * ((n_types // len(COLORS)) + 1))[:n_types]

    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(max(10, n_types * 1.4), 9), gridspec_kw={"hspace": 0.45}
    )

    # ── Top: overall distribution ──────────────────────────────────────────
    bars = ax_top.bar(
        type_order, pcts, color=palette, edgecolor=BG, linewidth=0.8, alpha=0.9
    )
    for bar, pct, count in zip(bars, pcts, counts):
        if pct > 1.5:
            ax_top.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.5,
                f"{pct:.1f}%\n({count:,})",
                ha="center",
                fontsize=9,
                color=DARK,
            )
    ax_top.set_ylabel("Share of All Cookies (%)")
    ax_top.set_title("Cookie Injection by Request Type")
    ax_top.set_ylim(0, pcts.max() * 1.25)
    ax_top.tick_params(axis="x", rotation=20)
    ax_top.grid(axis="y", alpha=0.35)
    ax_top.spines[["top", "right"]].set_visible(False)
    ax_top.text(
        0.99,
        0.97,
        f"n = {total:,} cookies with network context",
        transform=ax_top.transAxes,
        ha="right",
        va="top",
        fontsize=8.5,
        color=MID,
    )

    # ── Bottom: tracker share per type (requires is_tracker col) ──────────
    if "is_tracker" in cookies_df.columns:
        ctx2 = cookies_df[cookies_df["set_by_type"].notna()].copy()
        ctx2["set_by_type"] = ctx2["set_by_type"].str.lower()
        ctx2["is_tracker_bool"] = ctx2["is_tracker"].apply(
            lambda v: bool(v) if (v is not None and v is not False) else False
        )

        tracker_pcts, nont_pcts = [], []
        for t in type_order:
            sub = ctx2[ctx2["set_by_type"] == t]
            if len(sub) == 0:
                tracker_pcts.append(0)
                nont_pcts.append(0)
            else:
                tp = sub["is_tracker_bool"].mean() * 100
                tracker_pcts.append(tp)
                nont_pcts.append(100 - tp)

        x = np.arange(n_types)
        ax_bot.bar(
            x, tracker_pcts, color=ACCENT, label="Tracker", edgecolor=BG, linewidth=0.8
        )
        ax_bot.bar(
            x,
            nont_pcts,
            bottom=tracker_pcts,
            color=COLORS[2],
            label="Non-Tracker",
            edgecolor=BG,
            linewidth=0.8,
        )

        ax_bot.set_xticks(x)
        ax_bot.set_xticklabels(type_order, rotation=20, ha="right")
        ax_bot.set_ylim(0, 115)
        ax_bot.set_ylabel("% of Cookies in Each Type")
        ax_bot.set_title("Tracker Share by Request Type")
        ax_bot.legend(fontsize=9)
        ax_bot.grid(axis="y", alpha=0.35)
        ax_bot.spines[["top", "right"]].set_visible(False)
    else:
        ax_bot.set_visible(False)

    plt.tight_layout()
    save_figure(out_dir, "plot_cookie_set_by_type.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--out", default="./plots/third_party")
    args = parser.parse_args()
    plot_set_by_type(args.data, args.out)
