"""
Tracker Density Heatmap — delivery channel × party context

A matrix where:
  rows    = delivery channel  (bucketed setter_request_type / setter_type)
  columns = party context     (first-party / third-party / unknown)
  colour  = tracker density   (fraction of cookies in that cell that are
                               flagged by a tracker list, 0–1)

Each cell is also annotated with:
  top line   — tracker density as a %
  bottom line — raw cookie count (n=…)

Rows and columns are ordered by overall tracker density (highest at top/left)
so the hottest cells cluster in the top-left corner.

Reads raw cookie records via CookieDataset.iter_raw_sites() because
setter_request_type is not projected into the enriched cookies frame.

Usage:
    python scripts/plot_scripts/plot_tracker_heatmap.py
    python scripts/plot_scripts/plot_tracker_heatmap.py \
        --data cookies_data --country Netherlands --browser chromium \
        --out plots/heatmap
"""

import argparse
import os
import sys
from collections import defaultdict

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mc
from matplotlib.patches import Rectangle

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

_CHANNEL_BY_REQUEST_TYPE = {
    "Document": "Page load",
    "Image": "Tracking pixel",
    "Script": "Script tag",
    "Fetch": "Background call",
    "XHR": "Background call",
    "Ping": "Beacon",
    "SubDocument": "Iframe",
}

PARTY_LABELS = {
    "first_party": "First-party",
    "third_party": "Third-party",
    "unknown": "Unknown",
}


def _channel(setter_type: str, request_type) -> str:
    if setter_type == "http":
        # Use the human label when we have one; otherwise use the raw CDP type
        # as-is rather than collapsing everything into a single "Other" bucket.
        if request_type in _CHANNEL_BY_REQUEST_TYPE:
            return _CHANNEL_BY_REQUEST_TYPE[request_type]
        return request_type if request_type else "HTTP (no type)"
    if setter_type == "javascript":
        return "JS write"
    return "Unknown"


def _collect(ds, country, browser):
    from analysis.src.helpers import party_type

    # (party, channel) -> [total, trackers]
    counts: dict[tuple, list] = defaultdict(lambda: [0, 0])
    for site in ds.iter_raw_sites():
        if site.country != country or site.browser != browser:
            continue
        target_host = site.target_url.split("//")[-1].split("/")[0]
        for c in site.cookies:
            party = PARTY_LABELS.get(
                party_type(target_host, c.get("domain", "")), "Unknown"
            )
            setter = c.get("setter_type") or "unknown"
            ch = _channel(setter, c.get("setter_request_type"))
            is_trk = bool(c.get("tracker_lists"))
            counts[(party, ch)][0] += 1
            counts[(party, ch)][1] += int(is_trk)
    return counts


def plot_tracker_heatmap(
    data_dir: str, country: str, browser: str, out_dir: str
) -> None:
    apply_theme()
    ds = dataset(data_dir)
    counts = _collect(ds, country, browser)

    if not counts:
        print(f"No cookies found for {country}/{browser}.")
        return

    total = sum(v[0] for v in counts.values())

    # --- axis labels ---
    all_parties = sorted({k[0] for k in counts})
    all_channels = sorted({k[1] for k in counts})

    # Order rows (parties) by descending overall tracker density
    def _p_density(p):
        t = sum(counts.get((p, ch), [0, 0])[0] for ch in all_channels)
        trk = sum(counts.get((p, ch), [0, 0])[1] for ch in all_channels)
        return trk / t if t else 0.0

    # Order columns (channels) by descending overall tracker density
    def _ch_density(ch):
        t = sum(counts.get((p, ch), [0, 0])[0] for p in all_parties)
        trk = sum(counts.get((p, ch), [0, 0])[1] for p in all_parties)
        return trk / t if t else 0.0

    all_parties = sorted(all_parties, key=_p_density, reverse=True)
    all_channels = sorted(all_channels, key=_ch_density, reverse=True)

    nrows = len(all_parties)
    ncols = len(all_channels)

    # Build density + count matrices  (rows = party, cols = channel)
    density = np.zeros((nrows, ncols))
    raw_cnt = np.zeros((nrows, ncols), dtype=int)
    raw_trk = np.zeros((nrows, ncols), dtype=int)
    for r, p in enumerate(all_parties):
        for c, ch in enumerate(all_channels):
            cnt, trk = counts.get((p, ch), [0, 0])
            raw_cnt[r, c] = cnt
            raw_trk[r, c] = trk
            density[r, c] = trk / cnt if cnt else np.nan

    # --- colormap: BG (cream) → ACCENT (burnt orange) ---
    cmap = mc.LinearSegmentedColormap.from_list(
        "tracker_heat", [BG, ACCENT2, ACCENT, "#6b1d06"], N=256
    )
    cmap.set_bad(color=LIGHT)  # NaN cells (zero cookies) → light grey

    cell_w, cell_h = 1.8, 0.95
    bar_w = 2.5  # inches for the marginal bar panel
    cbar_w = 0.25  # inches for the colorbar
    fig_w = ncols * cell_w + bar_w + cbar_w + 3.0
    fig_h = nrows * cell_h + 2.2

    fig = plt.figure(figsize=(fig_w, fig_h))
    gs = fig.add_gridspec(
        1,
        3,
        width_ratios=[ncols * cell_w, bar_w, cbar_w],
        wspace=0.0,
    )
    ax = fig.add_subplot(gs[0])
    ax_bar = fig.add_subplot(gs[1])
    ax_cbar = fig.add_subplot(gs[2])

    im = ax.imshow(
        density,
        cmap=cmap,
        vmin=0.0,
        vmax=1.0,
        aspect="auto",
        zorder=1,
    )

    # Cell annotations
    for r in range(nrows):
        for c in range(ncols):
            cnt = raw_cnt[r, c]
            trk = raw_trk[r, c]
            if cnt == 0:
                ax.text(
                    c,
                    r,
                    "—",
                    ha="center",
                    va="center",
                    fontsize=10,
                    color=MID,
                    zorder=3,
                )
                continue
            d = density[r, c]
            # Choose text colour for contrast against the fill
            text_color = BG if d > 0.45 else DARK
            ax.text(
                c,
                r - 0.13,
                f"{d*100:.0f}%",
                ha="center",
                va="center",
                fontsize=12,
                fontweight="bold",
                color=text_color,
                zorder=3,
            )
            ax.text(
                c,
                r + 0.22,
                f"n={cnt:,}",
                ha="center",
                va="center",
                fontsize=8.5,
                color=text_color,
                zorder=3,
            )

    # Grid lines between cells
    for x in np.arange(-0.5, ncols, 1):
        ax.axvline(x, color=BG, linewidth=1.5, zorder=2)
    for y in np.arange(-0.5, nrows, 1):
        ax.axhline(y, color=BG, linewidth=1.5, zorder=2)

    # Axes
    ax.set_xticks(range(ncols))
    ax.set_xticklabels(
        all_channels,
        fontsize=10,
        fontweight="bold",
        color=DARK,
        rotation=0,
        ha="center",
        va="bottom",
    )
    ax.set_yticks(range(nrows))
    ax.set_yticklabels(all_parties, fontsize=12, fontweight="bold", color=DARK)
    ax.tick_params(length=0)
    ax.xaxis.set_ticks_position("top")
    ax.xaxis.set_label_position("top")
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Row marginals: overall tracker density per party, as a bar chart
    p_totals = raw_cnt.sum(axis=1)
    p_trackers = raw_trk.sum(axis=1)
    p_density = np.where(p_totals > 0, p_trackers / p_totals, 0.0)
    bar_colors = [cmap(d) for d in p_density]

    ax_bar.barh(
        range(nrows),
        p_density * 100,
        color=bar_colors,
        edgecolor=LIGHT,
        linewidth=0.8,
        height=0.65,
        zorder=2,
    )

    # Grid
    ax_bar.set_axisbelow(True)
    ax_bar.xaxis.grid(True, color=LIGHT, linewidth=0.8, linestyle="-", zorder=1)

    # Axes limits and ticks
    ax_bar.set_xlim(0, 100)
    ax_bar.set_ylim(-0.5, nrows - 0.5)
    ax_bar.invert_yaxis()
    ax_bar.set_yticks([])
    ax_bar.set_xticks([0, 25, 50, 75, 100])
    ax_bar.set_xticklabels(["0", "25", "50", "75", "100%"], fontsize=8, color=DARK)
    ax_bar.tick_params(axis="x", length=3, color=LIGHT, pad=2)

    # Spines: bottom + right form the outer border; left is flush with the
    # heatmap edge so hide it to avoid a doubled line; top hidden as usual.
    ax_bar.spines["top"].set_visible(False)
    ax_bar.spines["left"].set_visible(False)
    ax_bar.spines["right"].set_color(LIGHT)
    ax_bar.spines["bottom"].set_color(LIGHT)

    # Sync y-axis row positions with heatmap
    ax_bar.set_ylim(ax.get_ylim())

    ax_bar.set_xlabel("Tracker %", fontsize=9, color=DARK, labelpad=5)
    ax_bar.xaxis.set_label_position("bottom")
    ax_bar.xaxis.set_ticks_position("bottom")

    # Colorbar — pinned to its own GridSpec column so it never steals
    # space from the heatmap or the bar panel
    cbar = fig.colorbar(im, cax=ax_cbar)
    cbar.set_label("Tracker density", fontsize=10, color=DARK)
    cbar.set_ticks([0, 0.25, 0.5, 0.75, 1.0])
    cbar.set_ticklabels(["0%", "25%", "50%", "75%", "100%"])
    cbar.ax.yaxis.set_tick_params(color=DARK, labelsize=9)
    cbar.outline.set_visible(False)

    ax.set_title(
        f"Tracker Density ({country}/{browser})\n"
        f"delivery channel by party type  ({total:,} cookies total)",
        fontsize=14,
        fontweight="bold",
        pad=14,
        color=DARK,
    )

    plt.tight_layout()
    fname = f"plot_tracker_heatmap_{country.lower()}_{browser}"
    save_figure(out_dir, f"{fname}.png", f"{fname}.pdf")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--country", default="Netherlands")
    parser.add_argument("--browser", default="chromium")
    parser.add_argument("--out", default="./plots/heatmap")
    args = parser.parse_args()
    plot_tracker_heatmap(args.data, args.country, args.browser, args.out)
