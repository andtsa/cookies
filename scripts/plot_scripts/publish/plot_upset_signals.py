"""
UpSet plot — Tracker signal co-occurrence for confirmed/probable cookies.

Shows which combinations of detection signals appear together on the same
cookies, for all cookies classified as confirmed or probable trackers.

  Top-right    — Intersection size bars (sorted by count, largest on left)
  Bottom-right — Dot matrix (filled = signal active in that intersection)
  Bottom-left  — Set size bars (total cookies with each signal, grows left)
  Top-left     — Empty (reserved for title / suptitle breathing room)

Usage:
    python scripts/plot_scripts/plot_upset_signals.py
    python scripts/plot_scripts/plot_upset_signals.py \\
        --country Netherlands --browser chromium --out plots/upset
"""

import argparse
import os
import sys
from collections import Counter

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.transforms import blended_transform_factory

sys.path.insert(0, os.path.dirname(__file__))
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

_SIGNALS = [
    (
        "EasyPrivacy blocklist",
        lambda s: s.startswith("list:") and s not in ("list:nan", "list:OpenCookieDB"),
        "list",
    ),
    ("OpenCookieDB", lambda s: s in ("list:nan", "list:OpenCookieDB"), "list"),
    (
        "High entropy + persistent",
        lambda s: s == "capability:high_entropy+persistent",
        "capability",
    ),
    ("Third-party setter", lambda s: s == "context:set_by_third_party", "capability"),
    (
        "3P + long-lived + capable",
        lambda s: s == "context:third_party+long_lived+capable",
        "capability",
    ),
    (
        "Cross-site identifier sharing",
        lambda s: "identifier_shared_across" in s,
        "behavioural",
    ),
    ("Cookie syncing", lambda s: "cookie_syncing_confirmed" in s, "behavioural"),
    ("Cross-domain JS reads", lambda s: "js_read_across" in s, "behavioural"),
    ("Corroborated", lambda s: s.startswith("corroborated:"), "compound"),
]

# Two-line description shown below each signal name in the plot.
DESCRIPTIONS = {
    "EasyPrivacy blocklist": "Domain matched a rule in the\nEasyPrivacy filter list.",
    "OpenCookieDB": "Name matched the OpenCookieDB\ncrowd-sourced tracker database.",
    "High entropy + persistent": "Value appears to be a unique ID\nand the cookie lasts 7+ days.",
    "Third-party setter": "Cookie was set by a domain other\nthan the page being visited.",
    "3P + long-lived + capable": "Third-party origin, long expiry,\nand a high-entropy value.",
    "Cross-site identifier sharing": "The exact same value was seen on\n4 or more different websites.",
    "Cookie syncing": "Cookie value found embedded in an\noutgoing request to another domain.",
    "Cross-domain JS reads": "JavaScript reads this cookie across\nmultiple domains in the crawl.",
    "Corroborated": "Cookie is simultaneously list-matched,\nthird-party, and high-entropy.",
}

DESC_COLOR = "#7a5038"  # darker than MID, lighter than DARK


def _build_data(cc):
    combo_counts: Counter = Counter()
    signal_totals: Counter = Counter()
    for sigs in cc["tracker_signals"]:
        active = frozenset(
            label for label, match_fn, _ in _SIGNALS if any(match_fn(s) for s in sigs)
        )
        if active:
            combo_counts[active] += 1
            for label in active:
                signal_totals[label] += 1
    return combo_counts, signal_totals


def plot_upset_signals(data_dir, country, browser, out_dir, n_show=15):
    apply_theme()
    ds_obj = dataset(data_dir)
    cc = ds_obj.classified_cookies

    if country and browser:
        cc = cc[(cc["country"] == country) & (cc["browser"] == browser)]

    cc = cc[cc["tracker_tier"].isin(["confirmed", "probable"])]
    if cc.empty:
        print("No confirmed/probable tracker cookies found.")
        return

    combo_counts, signal_totals = _build_data(cc)

    _OMIT = {"Corroborated", "Cross-site identifier sharing"}

    # Signal order: most common at top (row 0 → top, y-axis inverted).
    signal_order = sorted(
        [lbl for lbl, _, _ in _SIGNALS if lbl in signal_totals and lbl not in _OMIT],
        key=lambda l: signal_totals[l],
        reverse=True,
    )
    n_sigs = len(signal_order)
    sig_to_row = {sig: i for i, sig in enumerate(signal_order)}

    top_combos = sorted(combo_counts.items(), key=lambda x: x[1], reverse=True)[:n_show]
    n_combos = len(top_combos)
    n_total = len(combo_counts)

    # ── Figure + GridSpec ──────────────────────────────────────────────────────
    cell_w = 0.80
    set_w = 3.2
    bar_h = 3.4
    dot_h = max(4.0, n_sigs * 0.82)  # ~0.82 in per row: tighter around signal titles

    fig = plt.figure(
        figsize=(
            max(14, set_w + n_combos * cell_w + 1.5),
            bar_h + dot_h + 0.8,
        )
    )
    gs = fig.add_gridspec(
        2,
        2,
        width_ratios=[set_w, n_combos * cell_w],
        height_ratios=[bar_h, dot_h],
        hspace=0.06,
        wspace=0.0,
    )

    ax_top = fig.add_subplot(gs[0, 0])
    ax_int = fig.add_subplot(gs[0, 1])
    ax_set = fig.add_subplot(gs[1, 0])
    ax_dot = fig.add_subplot(gs[1, 1])

    ax_top.axis("off")

    # Shared coordinate spaces
    dot_xlim = (-0.5, n_combos - 0.5)
    dot_ylim = (n_sigs - 0.5, -0.5)  # inverted: row 0 at top
    set_counts = [signal_totals.get(sig, 0) for sig in signal_order]
    max_set = max(set_counts) or 1

    # ── Dot matrix ────────────────────────────────────────────────────────────
    ax_dot.set_xlim(*dot_xlim)
    ax_dot.set_ylim(*dot_ylim)
    ax_dot.spines[:].set_visible(False)
    ax_dot.tick_params(left=False, labelleft=False, bottom=False, labelbottom=False)

    for i in range(n_sigs):
        if i % 2 == 0:
            ax_dot.axhspan(i - 0.5, i + 0.5, color=DARK, alpha=0.06, zorder=0)

    for col, (combo, _) in enumerate(top_combos):
        active = sorted(sig_to_row[s] for s in combo if s in sig_to_row)
        inactive = [i for i in range(n_sigs) if i not in active]

        if len(active) > 1:
            ax_dot.plot(
                [col, col],
                [active[0], active[-1]],
                color=ACCENT,
                lw=2.4,
                zorder=2,
                solid_capstyle="round",
            )
        for row in active:
            ax_dot.scatter(col, row, s=120, color=ACCENT, zorder=3, linewidths=0)
        for row in inactive:
            ax_dot.scatter(col, row, s=65, color=LIGHT, zorder=2, linewidths=0)

    # ── Intersection size bars ─────────────────────────────────────────────────
    ax_int.set_xlim(*dot_xlim)
    counts = [cnt for _, cnt in top_combos]
    max_cnt = max(counts)

    ax_int.bar(
        np.arange(n_combos),
        counts,
        color=ACCENT,
        width=0.68,
        edgecolor=BG,
        linewidth=0.4,
        zorder=2,
    )
    for x, cnt in zip(range(n_combos), counts):
        ax_int.text(
            x,
            cnt + max_cnt * 0.015,
            f"{cnt:,}",
            ha="center",
            va="bottom",
            fontsize=9.5,
            color=DARK,
        )

    ax_int.set_ylim(0, max_cnt * 1.22)
    ax_int.set_ylabel("Cookies in intersection", fontsize=12, color=DARK)
    ax_int.spines[["top", "right", "bottom"]].set_visible(False)
    ax_int.spines["left"].set_color(LIGHT)
    ax_int.tick_params(bottom=False, labelbottom=False, length=0)
    ax_int.yaxis.grid(True, color=LIGHT, linewidth=0.8)
    ax_int.set_axisbelow(True)

    # ── Set size bars ──────────────────────────────────────────────────────────
    ax_set.set_ylim(*dot_ylim)

    ax_set.barh(
        np.arange(n_sigs),
        set_counts,
        color=MID,
        height=0.35,
        edgecolor=BG,
        linewidth=0.4,
        zorder=2,
    )
    ax_set.invert_xaxis()
    ax_set.set_xlim(max_set * 1.28, 0)

    for i in range(n_sigs):
        if i % 2 == 0:
            ax_set.axhspan(i - 0.5, i + 0.5, color=DARK, alpha=0.06, zorder=0)

    # Signal name + description as blended-transform annotations.
    # x = axes fraction (-0.02 = just outside left edge); y = data coordinate.
    # With the inverted y-axis, y_data = i places the text at signal row i.
    lbl_tr = blended_transform_factory(ax_set.transAxes, ax_set.transData)
    for i, sig in enumerate(signal_order):
        ax_set.text(
            -0.02,
            i - 0.17,
            sig,
            transform=lbl_tr,
            ha="right",
            va="center",
            fontsize=12,
            fontweight="bold",
            color=DARK,
            clip_on=False,
        )
        ax_set.text(
            -0.02,
            i + 0.21,
            DESCRIPTIONS.get(sig, ""),
            transform=lbl_tr,
            ha="right",
            va="center",
            fontsize=9,
            fontstyle="italic",
            color=DESC_COLOR,
            clip_on=False,
            linespacing=1.45,
        )

    ax_set.set_yticks([])
    ax_set.set_xlabel("Set size (cookies)", fontsize=12, color=DARK)
    ax_set.spines[["top", "right", "left"]].set_visible(False)
    ax_set.spines["bottom"].set_color(LIGHT)
    ax_set.xaxis.grid(True, color=LIGHT, linewidth=0.8)
    ax_set.set_axisbelow(True)

    def _fmt_si(x, _):
        x = abs(x)
        for threshold, suffix in [(1e9, "B"), (1e6, "M"), (1e3, "K")]:
            if x >= threshold:
                return f"{x / threshold:g}{suffix}"
        return f"{x:g}"

    ax_set.xaxis.set_major_formatter(mticker.FuncFormatter(_fmt_si))
    ax_set.tick_params(length=0)

    # ── Title ──────────────────────────────────────────────────────────────────
    scope = f"{country} / {browser}" if country and browser else "all crawls"
    note = (
        f"top {n_show} of {n_total} combinations"
        if n_total > n_show
        else f"{n_total} combinations"
    )
    fig.suptitle(
        f"Tracker signal co-occurrence in {scope} "
        f"({len(cc):,} identified tracker cookies, {note})",
        fontsize=14,
        fontweight="bold",
        color=DARK,
    )

    fig_w = fig.get_size_inches()[0]
    left_frac = 4.2 / fig_w  # ~4.2 in for larger bold name + 2-line italic description
    fig.subplots_adjust(
        left=left_frac, right=0.99, top=0.94, bottom=0.07, hspace=0.06, wspace=0.0
    )
    slug = f"_{country.lower()}_{browser}" if country and browser else "_all"
    fname = f"plot_upset_signals{slug}"
    save_figure(out_dir, f"{fname}.png", f"{fname}.pdf")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--country", default=None)
    parser.add_argument("--browser", default=None)
    parser.add_argument("--n", type=int, default=15)
    parser.add_argument("--out", default="./plots/upset")
    args = parser.parse_args()
    plot_upset_signals(args.data, args.country, args.browser, args.out, n_show=args.n)
