"""
Tracker Delivery Pathways — back-to-back ("butterfly") bar chart

A symmetric two-sided chart where every delivery channel occupies one row,
with first-party cookies on the left and third-party cookies on the right.
The channel label sits in the centre spine so both sides share the same
vertical axis, making first/third-party comparisons direct and unambiguous.

Each side has two bars per channel:
  gold bar   — total cookies on that route  (annotated: % of all cookies)
  orange bar — tracker-flagged cookies       (annotated: % tracker share)

"Unknown" party cookies are appended below a divider at the bottom rather
than forcing them onto one side.

Usage:
    python scripts/plot_scripts/plot_tracker_pathways_bars.py
    python scripts/plot_scripts/plot_tracker_pathways_bars.py \
        --data cookies_data --country Netherlands --browser chromium \
        --out plots/pathways
"""

import argparse
import os
import sys
from collections import defaultdict

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.lines as mlines

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


def _channel(setter_type: str, request_type) -> str:
    if setter_type == "http":
        return _CHANNEL_BY_REQUEST_TYPE.get(
            request_type, f"Other ({request_type or '—'})"
        )
    if setter_type == "javascript":
        return "JS write"
    return "Unknown"


def _collect(ds, country, browser):
    from analysis.src.helpers import party_type

    counts: dict[tuple, list] = defaultdict(lambda: [0, 0])
    for site in ds.iter_raw_sites():
        if site.country != country or site.browser != browser:
            continue
        target_host = site.target_url.split("//")[-1].split("/")[0]
        for c in site.cookies:
            party = party_type(target_host, c.get("domain", ""))
            setter_type = c.get("setter_type") or "unknown"
            channel = _channel(setter_type, c.get("setter_request_type"))
            is_trk = bool(c.get("tracker_lists"))
            counts[(party, channel)][0] += 1
            counts[(party, channel)][1] += int(is_trk)
    return counts


def _side_bars(ax, channel_rows, side, full_w, total, bar_h, group_h):
    """Draw a full-width stacked bar per channel: non-tracker | tracker.

    Every bar spans the full width ``full_w`` regardless of cookie count —
    the split point marks what fraction are tracker-flagged. This makes the
    tracker share readable even on low-count routes.

    Actual cookie counts are shown prominently inside the bar; the tracker %
    is annotated at the split boundary.

    ``side`` is ``"left"`` (bars extend in -x) or ``"right"`` (bars extend in +x).
    Non-tracker segment: ACCENT2 (gold).
    Tracker segment:     ACCENT  (burnt orange).
    """
    sign = -1 if side == "left" else 1
    n = len(channel_rows)
    ha_in = "right" if side == "left" else "left"  # towards spine
    ha_out = "left" if side == "left" else "right"  # away from spine

    for i, (channel, cnt, trk) in enumerate(channel_rows):
        non_trk = cnt - trk
        y = (n - 1 - i) * group_h
        frac_trk = trk / cnt if cnt else 0.0
        w_non = full_w * (1 - frac_trk)
        w_trk = full_w * frac_trk

        # Non-tracker segment
        ax.barh(
            y,
            sign * w_non,
            height=bar_h,
            color=ACCENT2,
            edgecolor=BG,
            linewidth=0.5,
            zorder=2,
        )
        # Tracker segment
        if w_trk > 0:
            ax.barh(
                y,
                sign * w_trk,
                left=sign * w_non,
                height=bar_h,
                color=ACCENT,
                edgecolor=BG,
                linewidth=0.5,
                zorder=2,
            )

        # Dotted divider at the split
        if 0 < frac_trk < 1:
            bx = sign * w_non
            ax.plot(
                [bx, bx],
                [y - bar_h / 2, y + bar_h / 2],
                color=DARK,
                linewidth=1.4,
                linestyle=":",
                zorder=3,
                solid_capstyle="round",
            )

        # Tracker % label at the split (inside the tracker segment if wide
        # enough, otherwise just outside the non-tracker segment)
        if trk > 0:
            pct_trk = frac_trk * 100
            split_x = sign * w_non
            if w_trk >= full_w * 0.08:
                ax.text(
                    split_x + sign * w_trk * 0.5,
                    y,
                    f"{pct_trk:.0f}%\ntrk",
                    ha="center",
                    va="center",
                    fontsize=7.5,
                    color=BG,
                    fontweight="bold",
                    zorder=4,
                )
            else:
                # Tiny tracker segment — label outside the bar tip
                ax.text(
                    sign * (full_w + full_w * 0.03),
                    y,
                    f"{pct_trk:.0f}% trk",
                    ha=ha_out,
                    va="center",
                    fontsize=7.5,
                    color=ACCENT,
                    fontweight="bold",
                    zorder=4,
                )

        # Cookie count — large, prominent, in the non-tracker segment
        # (or centred if bar is 100% tracker)
        count_x = sign * w_non * 0.5 if w_non >= full_w * 0.15 else sign * full_w * 0.5
        ax.text(
            count_x,
            y,
            f"{cnt:,}",
            ha="center",
            va="center",
            fontsize=10,
            color=DARK,
            fontweight="bold",
            zorder=4,
        )


def plot_tracker_pathways_bars(
    data_dir: str, country: str, browser: str, out_dir: str
) -> None:
    apply_theme()
    ds = dataset(data_dir)
    counts = _collect(ds, country, browser)

    if not counts:
        print(f"No cookies found for {country}/{browser}.")
        return

    total = sum(v[0] for v in counts.values())

    # Split into first-party, third-party, unknown
    fp: dict[str, list] = defaultdict(lambda: [0, 0])
    tp: dict[str, list] = defaultdict(lambda: [0, 0])
    unk: dict[str, list] = defaultdict(lambda: [0, 0])
    for (party, channel), (cnt, trk) in counts.items():
        if party == "first_party":
            fp[channel][0] += cnt
            fp[channel][1] += trk
        elif party == "third_party":
            tp[channel][0] += cnt
            tp[channel][1] += trk
        else:
            unk[channel][0] += cnt
            unk[channel][1] += trk

    # Union of channels, ordered by combined total desc
    all_channels = sorted(
        set(fp) | set(tp),
        key=lambda ch: fp.get(ch, [0])[0] + tp.get(ch, [0])[0],
        reverse=True,
    )
    unk_channels = sorted(unk, key=lambda ch: unk[ch][0], reverse=True)

    max_val = (
        max(
            max((v[0] for v in fp.values()), default=0),
            max((v[0] for v in tp.values()), default=0),
        )
        or 1
    )
    # All bars are drawn at this fixed width; the split marks tracker fraction.
    full_w = max_val

    bar_h = 0.55
    group_h = 1.0
    n_main = len(all_channels)
    n_unk = len(unk_channels)
    n_rows = n_main + (n_unk + 1 if n_unk else 0)  # +1 for divider gap

    fig_h = max(6, n_rows * group_h + 2.0)
    fig, ax = plt.subplots(figsize=(15, fig_h))

    # --- main rows (shared channels, both sides) ---
    fp_rows = [
        (ch, fp.get(ch, [0, 0])[0], fp.get(ch, [0, 0])[1]) for ch in all_channels
    ]
    tp_rows = [
        (ch, tp.get(ch, [0, 0])[0], tp.get(ch, [0, 0])[1]) for ch in all_channels
    ]

    _side_bars(ax, fp_rows, "left", full_w, total, bar_h, group_h)
    _side_bars(ax, tp_rows, "right", full_w, total, bar_h, group_h)

    # Centre channel labels
    for i, ch in enumerate(all_channels):
        y_mid = (n_main - 1 - i) * group_h
        ax.text(
            0,
            y_mid,
            ch,
            ha="center",
            va="center",
            fontsize=10,
            fontweight="bold",
            color=DARK,
            zorder=4,
            bbox=dict(
                boxstyle="round,pad=0.25", facecolor=BG, edgecolor=LIGHT, linewidth=0.8
            ),
        )

    # --- unknown rows below a divider ---
    if n_unk:
        div_y = -group_h * 0.9
        ax.axhline(div_y, color=LIGHT, linewidth=1.2, linestyle="--", zorder=1)
        ax.text(
            0,
            div_y - group_h * 0.35,
            "unknown party",
            ha="center",
            va="center",
            fontsize=9,
            color=MID,
            style="italic",
        )

        unk_rows = [(ch, unk[ch][0], unk[ch][1]) for ch in unk_channels]
        # Shift unknown rows below the divider using a simple offset transform.
        y_offset = -(n_main) * group_h - group_h
        for j, (ch, cnt, trk) in enumerate(unk_rows):
            y = y_offset + (n_unk - 1 - j) * group_h
            frac_trk = trk / cnt if cnt else 0.0
            w_non = full_w * (1 - frac_trk)
            w_trk = full_w * frac_trk
            ax.barh(
                y,
                w_non,
                height=bar_h,
                color=ACCENT2,
                edgecolor=BG,
                linewidth=0.5,
                zorder=2,
            )
            if w_trk > 0:
                ax.barh(
                    y,
                    w_trk,
                    left=w_non,
                    height=bar_h,
                    color=ACCENT,
                    edgecolor=BG,
                    linewidth=0.5,
                    zorder=2,
                )
            if 0 < frac_trk < 1:
                ax.plot(
                    [w_non, w_non],
                    [y - bar_h / 2, y + bar_h / 2],
                    color=DARK,
                    linewidth=1.4,
                    linestyle=":",
                    zorder=3,
                )
            ax.text(
                full_w * 0.5,
                y,
                f"{cnt:,}",
                ha="center",
                va="center",
                fontsize=10,
                color=DARK,
                fontweight="bold",
                zorder=4,
            )
            ax.text(
                0,
                y,
                ch,
                ha="center",
                va="center",
                fontsize=9,
                fontweight="bold",
                color=DARK,
                zorder=4,
                bbox=dict(
                    boxstyle="round,pad=0.2",
                    facecolor=BG,
                    edgecolor=LIGHT,
                    linewidth=0.8,
                ),
            )

    # Column headers
    header_y = n_main * group_h + 0.3
    ax.text(
        -full_w * 0.5,
        header_y,
        "First-party",
        ha="center",
        va="bottom",
        fontsize=12,
        fontweight="bold",
        color=DARK,
    )
    ax.text(
        full_w * 0.5,
        header_y,
        "Third-party",
        ha="center",
        va="bottom",
        fontsize=12,
        fontweight="bold",
        color=DARK,
    )

    # Centre spine
    ax.axvline(0, color=LIGHT, linewidth=1.0, zorder=1)

    ax.set_xlim(-full_w * 1.25, full_w * 1.25)
    ax.set_ylim(-(n_unk + 2) * group_h, (n_main + 1) * group_h)
    ax.axis("off")

    ax.legend(
        handles=[
            mpatches.Patch(facecolor=ACCENT2, label="Not tracker-flagged"),
            mpatches.Patch(facecolor=ACCENT, label="Tracker-flagged"),
            mlines.Line2D(
                [],
                [],
                color=DARK,
                linewidth=1.2,
                linestyle=":",
                label="Tracker / non-tracker boundary",
            ),
        ],
        loc="lower center",
        bbox_to_anchor=(0.5, -0.04),
        ncol=2,
        fontsize=10,
        frameon=True,
    )

    ax.set_title(
        f"Tracker Delivery Pathways — {country} / {browser}  ({total:,} cookies total)",
        fontsize=15,
        fontweight="bold",
        pad=14,
    )
    plt.tight_layout()
    fname = f"plot_tracker_pathways_bars_{country.lower()}_{browser}"
    save_figure(out_dir, f"{fname}.png", f"{fname}.pdf")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--country", default="Netherlands")
    parser.add_argument("--browser", default="chromium")
    parser.add_argument("--out", default="./plots/pathways")
    args = parser.parse_args()
    plot_tracker_pathways_bars(args.data, args.country, args.browser, args.out)
