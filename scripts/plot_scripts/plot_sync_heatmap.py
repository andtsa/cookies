"""
Cookie-Sync Subtype Heatmap

Matrix of top receiving domains (rows) x a subtype dimension (columns), each cell
shaded by the number of sync rows. Good for spotting which collector domains favour
which mechanism (default columns = carrier), or how the confidence tiers / tracker
status distribute across collectors (--cols).

Subtype rows come from the analysis engine (CookieDataset.sync_subtype_rows,
cached by scripts/annotate.py); see scripts/plot_scripts/sync_subtypes.py.

Usage:
    python scripts/plot_scripts/plot_sync_heatmap.py --data cookies_data --out plots/syncing --top 20 --cols carrier
"""

import argparse
import os
import sys
from collections import Counter, defaultdict

import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

sys.path.insert(0, os.path.dirname(__file__))
import sync_subtypes as ss
from utils import apply_theme, save_figure, BG, ACCENT, DARK


# Sequential, on-theme colormap: pale background -> primary accent -> dark.
_CMAP = LinearSegmentedColormap.from_list("sync_seq", [BG, ACCENT, DARK])


def plot_heatmap(data_dir: str, out_dir: str, top: int, cols: str) -> None:
    apply_theme()
    events = ss.load_sync_events(data_dir)
    if cols not in ss.DIMENSIONS:
        raise SystemExit(f"--cols must be one of {list(ss.DIMENSIONS)}")
    order, _colors = ss.DIMENSIONS[cols]

    rows = [e for e in events if ss.dim_value(e, cols) is not None]
    if not rows:
        raise SystemExit(f"No events carry a '{cols}' value.")

    dom_totals = Counter(e["to_domain"] for e in rows)
    domains = [d for d, _ in dom_totals.most_common(top)]
    keep = set(domains)

    grid: dict[str, Counter] = defaultdict(Counter)
    for e in rows:
        if e["to_domain"] in keep:
            grid[e["to_domain"]][ss.dim_value(e, cols)] += 1

    categories = [c for c in order if any(grid[d].get(c) for d in domains)]
    categories += sorted(
        {c for d in domains for c in grid[d] if c not in order}
    )

    matrix = [[grid[d].get(c, 0) for c in categories] for d in domains]

    fig, ax = plt.subplots(
        figsize=(max(7, 1.1 * len(categories) + 3), max(6, 0.42 * len(domains) + 2))
    )
    im = ax.imshow(matrix, aspect="auto", cmap=_CMAP)

    ax.set_xticks(range(len(categories)))
    ax.set_xticklabels(categories, rotation=30, ha="right", fontsize=10)
    ax.set_yticks(range(len(domains)))
    ax.set_yticklabels(domains, fontsize=9)
    ax.set_title(f"Cookie-Sync: receiving domain x {cols}", fontsize=16, fontweight="bold", pad=12)

    # Annotate each cell; pick a legible text color against the cell shade.
    vmax = max((v for r in matrix for v in r), default=1) or 1
    for i, r in enumerate(matrix):
        for j, v in enumerate(r):
            if v:
                ax.text(
                    j, i, str(v), ha="center", va="center", fontsize=8,
                    color="white" if v > 0.55 * vmax else DARK,
                )

    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label("sync rows (per-param)", fontsize=10)
    plt.tight_layout()
    save_figure(out_dir, f"plot_sync_heatmap_{cols}.png", f"plot_sync_heatmap_{cols}.pdf")

    ss.print_subtype_report(events)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--out", default="./plots/syncing")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--cols", default="carrier", choices=list(ss.DIMENSIONS))
    args = parser.parse_args()
    plot_heatmap(args.data, args.out, args.top, args.cols)
