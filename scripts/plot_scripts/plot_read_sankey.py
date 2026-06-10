"""
Cross-Domain Read Flow (Sankey)

Three-stage flow showing who reads which cookies across domains:

    cookie name  ->  reader domain  ->  reader script (basename)

Ribbon thickness is the number of (cookie, reader_domain, script) read
observations. Cookie names and reader scripts are capped to top-N by volume;
the remainder folds into "(other)". Reader domains stay full and carry the
ribbon colour.

The read rows come from the analysis engine's on-disk-cached
``CookieDataset.third_party_reads`` (the ``tpreads`` relational cache) — same
loading path the sync plots use — so this never re-derives the JS-stack reads
when a cache is present.

Usage:
    python scripts/plot_scripts/plot_read_sankey.py --data cookies_data --out plots/reads --top 12
"""

import argparse
import os
import sys
from collections import Counter
from urllib.parse import urlparse

import matplotlib.pyplot as plt
from matplotlib.path import Path
from matplotlib.patches import PathPatch

sys.path.insert(0, os.path.dirname(__file__))
from utils import apply_theme, save_figure, dataset, DARK, MID, BG, COLORS  # noqa: E402

GAP = 0.015  # vertical gap between stacked nodes (axis fraction)
NODE_W = 0.035  # node rectangle width (axis fraction)
RIBBON_ALPHA = 0.45


def _script_label(url: str) -> str:
    """Shorten a script URL to 'netloc/basename' for a legible node label."""
    try:
        p = urlparse(url)
        basename = p.path.rstrip("/").rsplit("/", 1)[-1] or p.netloc
        return f"{p.netloc}/{basename}" if p.netloc else (basename or url)
    except Exception:
        return url


def _layout_column(nodes: list[tuple[str, int]], unit: float) -> dict[str, list]:
    """Top-align a column of (label, total) nodes; return label -> [y0, y1, top]."""
    pos = {}
    y = 1.0
    for label, total in nodes:
        h = total * unit
        pos[label] = [y - h, y, y]
        y -= h + GAP
    return pos


def _ribbon(ax, x0, x1, y0_l, y1_l, y0_r, y1_r, color):
    """Filled Bezier band between left edge [y0_l,y1_l] and right edge [y0_r,y1_r]."""
    cx = (x0 + x1) / 2.0
    verts = [
        (x0, y1_l),
        (cx, y1_l),
        (cx, y1_r),
        (x1, y1_r),
        (x1, y0_r),
        (cx, y0_r),
        (cx, y0_l),
        (x0, y0_l),
        (x0, y1_l),
    ]
    codes = [
        Path.MOVETO,
        Path.CURVE4,
        Path.CURVE4,
        Path.CURVE4,
        Path.LINETO,
        Path.CURVE4,
        Path.CURVE4,
        Path.CURVE4,
        Path.CLOSEPOLY,
    ]
    ax.add_patch(
        PathPatch(
            Path(verts, codes), facecolor=color, edgecolor="none", alpha=RIBBON_ALPHA
        )
    )


def plot_read_sankey(data_dir: str, out_dir: str, top: int) -> None:
    apply_theme()
    # Cached relational pass (loads the on-disk ``tpreads`` table when present).
    rows = dataset(data_dir).third_party_reads()
    if not rows:
        raise SystemExit("No third-party cookie reads found.")

    events = [
        {
            "cookie": r["cookie_name"],
            "reader_domain": r["reader_domain"],
            "script": _script_label(r.get("reader_script") or ""),
        }
        for r in rows
    ]
    total = len(events)

    # Fold cookie names / scripts to top-N + (other); reader domains stay full.
    cookie_keep = {c for c, _ in Counter(e["cookie"] for e in events).most_common(top)}
    script_keep = {s for s, _ in Counter(e["script"] for e in events).most_common(top)}

    def fold(val: str, keep: set) -> str:
        return val if val in keep else "(other)"

    folded = [
        {
            "cookie": fold(e["cookie"], cookie_keep),
            "reader_domain": e["reader_domain"],
            "script": fold(e["script"], script_keep),
        }
        for e in events
    ]

    # Flows between the three stages.
    f_cr = Counter(
        (e["cookie"], e["reader_domain"]) for e in folded
    )  # cookie -> reader
    f_rs = Counter(
        (e["reader_domain"], e["script"]) for e in folded
    )  # reader -> script

    # Node orders, each by volume.
    col0_nodes = Counter(e["cookie"] for e in folded).most_common()
    col1_nodes = Counter(e["reader_domain"] for e in folded).most_common()
    col2_nodes = Counter(e["script"] for e in folded).most_common()
    col0_order = [n for n, _ in col0_nodes]
    col1_order = [n for n, _ in col1_nodes]
    col2_order = [n for n, _ in col2_nodes]

    # One unit-per-observation scale shared by all columns; reserve room for gaps.
    max_nodes = max(len(col0_nodes), len(col1_nodes), len(col2_nodes))
    unit = (1.0 - (max_nodes - 1) * GAP) / total

    x0, x1, x2 = 0.0, 0.5, 1.0
    p0 = _layout_column(col0_nodes, unit)
    p1 = _layout_column(col1_nodes, unit)
    p2 = _layout_column(col2_nodes, unit)

    # Colour ribbons by reader domain (the middle stage that fans both ways).
    domain_colors = {d: COLORS[i % len(COLORS)] for i, d in enumerate(col1_order)}

    fig, ax = plt.subplots(figsize=(16, max(8, 0.5 * max_nodes + 4)))
    box = dict(
        facecolor=BG, edgecolor="none", alpha=0.78, pad=1.2, boxstyle="round,pad=0.2"
    )

    def _draw_nodes(pos, x, align):
        for label, (yb, yt, _top) in pos.items():
            color = domain_colors.get(label, DARK) if align == "center" else DARK
            ax.add_patch(
                plt.Rectangle(
                    (x, yb),
                    NODE_W,
                    yt - yb,
                    facecolor=color,
                    edgecolor=BG,
                    linewidth=0.5,
                )
            )
            ymid = (yb + yt) / 2.0
            short = label if len(label) <= 30 else label[:28] + ".."
            if align == "left":
                ax.text(
                    x - 0.008,
                    ymid,
                    short,
                    ha="right",
                    va="center",
                    fontsize=7.5,
                    color=DARK,
                )
            elif align == "right":
                ax.text(
                    x + NODE_W + 0.008,
                    ymid,
                    short,
                    ha="left",
                    va="center",
                    fontsize=7.5,
                    color=DARK,
                )
            else:
                ax.text(
                    x + NODE_W / 2,
                    ymid,
                    short,
                    ha="center",
                    va="center",
                    fontsize=7.5,
                    color=DARK,
                    bbox=box,
                    zorder=5,
                )

    _draw_nodes(p0, x0, "left")
    _draw_nodes(p1, x1, "center")
    _draw_nodes(p2, x2, "right")

    # Out/in cursors track how far down each node's edge we've consumed.
    out0 = {n: p0[n][1] for n in col0_order}  # cookie right edge
    in1 = {n: p1[n][1] for n in col1_order}  # reader left edge
    out1 = {n: p1[n][1] for n in col1_order}  # reader right edge
    in2 = {n: p2[n][1] for n in col2_order}  # script left edge

    # Stage 1: cookie -> reader domain, nested cookie(outer) x reader(inner).
    for c in col0_order:
        for d in col1_order:
            w = f_cr.get((c, d), 0)
            if not w:
                continue
            h = w * unit
            yl1, yl0 = out0[c], out0[c] - h
            yr1, yr0 = in1[d], in1[d] - h
            _ribbon(ax, x0 + NODE_W, x1, yl0, yl1, yr0, yr1, domain_colors.get(d, MID))
            out0[c] -= h
            in1[d] -= h

    # Stage 2: reader domain -> script, nested reader(outer) x script(inner).
    for d in col1_order:
        for s in col2_order:
            w = f_rs.get((d, s), 0)
            if not w:
                continue
            h = w * unit
            yl1, yl0 = out1[d], out1[d] - h
            yr1, yr0 = in2[s], in2[s] - h
            _ribbon(ax, x1 + NODE_W, x2, yl0, yl1, yr0, yr1, domain_colors.get(d, MID))
            out1[d] -= h
            in2[s] -= h

    from matplotlib.patches import Patch

    ax.legend(
        handles=[
            Patch(facecolor=domain_colors[d], label=d, alpha=RIBBON_ALPHA)
            for d in col1_order
        ],
        title="reader domain",
        loc="lower center",
        bbox_to_anchor=(0.5, -0.10),
        ncol=min(len(col1_order), 5),
        fontsize=8,
        title_fontsize=9,
    )

    ax.set_xlim(-0.18, 1.18)
    ax.set_ylim(-0.04, 1.08)
    ax.axis("off")

    ax.text(
        x0 + NODE_W / 2,
        1.04,
        "cookie name",
        ha="center",
        va="bottom",
        fontsize=11,
        fontweight="bold",
        color=DARK,
    )
    ax.text(
        x1 + NODE_W / 2,
        1.04,
        "reader domain",
        ha="center",
        va="bottom",
        fontsize=11,
        fontweight="bold",
        color=DARK,
    )
    ax.text(
        x2 + NODE_W / 2,
        1.04,
        "reader script",
        ha="center",
        va="bottom",
        fontsize=11,
        fontweight="bold",
        color=DARK,
    )

    ax.set_title(
        f"Cross-Domain Cookie Read Flow   (top {top} names/scripts,  {total:,} reads)",
        fontsize=15,
        fontweight="bold",
        pad=18,
    )
    plt.tight_layout()
    save_figure(out_dir, "plot_read_sankey.png", "plot_read_sankey.pdf")
    print(
        f"Plotted {total:,} cross-domain read observations across {len(col1_nodes)} reader domains."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--out", default="./plots/reads")
    parser.add_argument("--top", type=int, default=12)
    args = parser.parse_args()
    plot_read_sankey(args.data, args.out, args.top)
