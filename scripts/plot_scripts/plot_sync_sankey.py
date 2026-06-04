"""
Cookie-Sync Flow (Sankey)

A three-stage flow of where synced identifiers go and how they travel:

    source domain  ->  carrier (mechanism)  ->  receiving domain

Ribbon thickness is the number of sync rows (per-param) along that path; ribbons are
coloured by carrier (pixel / beacon / script / xhr-fetch / redirect-navigation /
other). Source and receiving domains are capped to the top-N by volume with the
remainder folded into "(other)", so the diagram stays legible.

Hand-rolled in matplotlib (no plotly dependency) so it shares the project theme and
the PNG+PDF save pipeline. Reads the ``cookie_syncing`` annotations that
scripts/find_cookie_syncing.py writes; see sync_subtypes.py for subtype derivation.

Usage:
    python scripts/plot_scripts/plot_sync_sankey.py --data cookies_data/chromium --out plots/syncing --top 12
"""

import argparse
import os
import sys
from collections import Counter

import matplotlib.pyplot as plt
from matplotlib.path import Path
from matplotlib.patches import PathPatch

sys.path.insert(0, os.path.dirname(__file__))
import sync_subtypes as ss
from utils import apply_theme, save_figure, DARK, MID, BG

GAP = 0.015          # vertical gap between stacked nodes (axis fraction)
NODE_W = 0.035       # node rectangle width (axis fraction)
RIBBON_ALPHA = 0.5


def _layout_column(nodes: list[tuple[str, int]], unit: float) -> dict[str, list]:
    """Top-align a column of (label, total) nodes; return label -> [y0, y1, top]."""
    pos = {}
    y = 1.0
    for label, total in nodes:
        h = total * unit
        pos[label] = [y - h, y, y]  # y_bottom, y_top, (mutable out-cursor set later)
        y -= h + GAP
    return pos


def _ribbon(ax, x0, x1, y0_l, y1_l, y0_r, y1_r, color):
    """Filled Bezier band between left edge [y0_l,y1_l] and right edge [y0_r,y1_r]."""
    cx = (x0 + x1) / 2.0
    verts = [
        (x0, y1_l),                       # start top-left
        (cx, y1_l), (cx, y1_r), (x1, y1_r),   # top edge curve
        (x1, y0_r),                       # down right edge
        (cx, y0_r), (cx, y0_l), (x0, y0_l),   # bottom edge curve back
        (x0, y1_l),                       # close
    ]
    codes = [
        Path.MOVETO,
        Path.CURVE4, Path.CURVE4, Path.CURVE4,
        Path.LINETO,
        Path.CURVE4, Path.CURVE4, Path.CURVE4,
        Path.CLOSEPOLY,
    ]
    ax.add_patch(
        PathPatch(Path(verts, codes), facecolor=color, edgecolor="none", alpha=RIBBON_ALPHA)
    )


def plot_sankey(data_dir: str, out_dir: str, top: int) -> None:
    apply_theme()
    events = ss.load_sync_events(data_dir)
    total = len(events)
    if not total:
        raise SystemExit("No sync events to plot.")

    # Fold source/receiving domains to top-N + (other); carriers stay full.
    src_totals = Counter(e["from_domain"] for e in events)
    dst_totals = Counter(e["to_domain"] for e in events)
    src_keep = set(d for d, _ in src_totals.most_common(top))
    dst_keep = set(d for d, _ in dst_totals.most_common(top))

    def src(e):
        return ss.fold_other(e["from_domain"], src_keep)

    def dst(e):
        return ss.fold_other(e["to_domain"], dst_keep)

    # Flows between the three stages.
    f_sc = Counter((src(e), e["carrier"]) for e in events)      # source -> carrier
    f_ct = Counter((e["carrier"], dst(e)) for e in events)      # carrier -> dest

    # Node orders: domains by volume; carriers by canonical vocabulary.
    col0 = Counter()
    col2 = Counter()
    for e in events:
        col0[src(e)] += 1
        col2[dst(e)] += 1
    col0_nodes = col0.most_common()
    col2_nodes = col2.most_common()
    col1_nodes = [(c, sum(v for (cc, _), v in f_ct.items() if cc == c))
                  for c in ss.CARRIERS if any(cc == c for (cc, _) in f_ct)]

    col0_order = [n for n, _ in col0_nodes]
    col1_order = [n for n, _ in col1_nodes]
    col2_order = [n for n, _ in col2_nodes]

    # One unit-per-event scale shared by all columns; reserve room for the gappiest.
    max_nodes = max(len(col0_nodes), len(col1_nodes), len(col2_nodes))
    unit = (1.0 - (max_nodes - 1) * GAP) / total

    x0, x1, x2 = 0.0, 0.5, 1.0
    p0 = _layout_column(col0_nodes, unit)
    p1 = _layout_column(col1_nodes, unit)
    p2 = _layout_column(col2_nodes, unit)

    fig, ax = plt.subplots(figsize=(14, max(7, 0.5 * max_nodes + 3)))

    # Draw node rectangles.
    box = dict(facecolor=BG, edgecolor="none", alpha=0.78, pad=1.2, boxstyle="round,pad=0.2")

    def _draw_nodes(pos, x, align):
        for label, (yb, yt, _top) in pos.items():
            ax.add_patch(plt.Rectangle((x, yb), NODE_W, yt - yb, facecolor=DARK, edgecolor=BG, linewidth=0.5))
            ymid = (yb + yt) / 2.0
            if align == "left":
                ax.text(x - 0.008, ymid, label, ha="right", va="center", fontsize=8, color=DARK)
            elif align == "right":
                ax.text(x + NODE_W + 0.008, ymid, label, ha="left", va="center", fontsize=8, color=DARK)
            else:
                # Carrier column sits amid ribbons: a backing box keeps it legible.
                ax.text(x + NODE_W / 2, ymid, label, ha="center", va="center",
                        fontsize=8, color=DARK, bbox=box, zorder=5)

    _draw_nodes(p0, x0, "left")
    _draw_nodes(p1, x1, "center")
    _draw_nodes(p2, x2, "right")

    # Out/in cursors track how far down each node's edge we've consumed.
    out0 = {n: p0[n][1] for n in col0_order}      # source right edge
    in1 = {n: p1[n][1] for n in col1_order}        # carrier left edge
    out1 = {n: p1[n][1] for n in col1_order}       # carrier right edge
    in2 = {n: p2[n][1] for n in col2_order}        # dest left edge

    # Stage 1: source -> carrier, nested source(outer) x carrier(inner).
    for s in col0_order:
        for c in col1_order:
            w = f_sc.get((s, c), 0)
            if not w:
                continue
            h = w * unit
            yl1, yl0 = out0[s], out0[s] - h
            yr1, yr0 = in1[c], in1[c] - h
            _ribbon(ax, x0 + NODE_W, x1, yl0, yl1, yr0, yr1, ss.CARRIER_COLORS.get(c, MID))
            out0[s] -= h
            in1[c] -= h

    # Stage 2: carrier -> dest, nested carrier(outer) x dest(inner).
    for c in col1_order:
        for d in col2_order:
            w = f_ct.get((c, d), 0)
            if not w:
                continue
            h = w * unit
            yl1, yl0 = out1[c], out1[c] - h
            yr1, yr0 = in2[d], in2[d] - h
            _ribbon(ax, x1 + NODE_W, x2, yl0, yl1, yr0, yr1, ss.CARRIER_COLORS.get(c, MID))
            out1[c] -= h
            in2[d] -= h

    from matplotlib.patches import Patch
    ax.legend(
        handles=[Patch(facecolor=ss.CARRIER_COLORS[c], label=c, alpha=RIBBON_ALPHA) for c in col1_order],
        title="carrier", loc="lower center", bbox_to_anchor=(0.5, -0.08),
        ncol=len(col1_order), fontsize=9, title_fontsize=10,
    )
    ax.set_xlim(-0.12, 1.12)
    ax.set_ylim(-0.02, 1.06)
    ax.axis("off")
    ax.set_title(
        f"Cookie-Sync Flow:  source  ->  carrier  ->  receiver   (top {top} domains/side)",
        fontsize=16, fontweight="bold", pad=10,
    )
    plt.tight_layout()
    save_figure(out_dir, "plot_sync_sankey.png", "plot_sync_sankey.pdf")

    ss.print_subtype_report(events)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data/chromium")
    parser.add_argument("--out", default="./plots/syncing")
    parser.add_argument("--top", type=int, default=12)
    args = parser.parse_args()
    plot_sankey(args.data, args.out, args.top)
