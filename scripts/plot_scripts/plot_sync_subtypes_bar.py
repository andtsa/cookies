"""
Cookie-Sync Subtype Composition (stacked bars)

One bar per top receiving domain (the "ID collectors"), plus an aggregate ALL bar,
stacked by a chosen subtype dimension. Default stacks by evidence **tier**
(confirmed > endpoint-named > candidate), which folds the URL/param-name regex
layer into the confidence ladder; switch with --by to break down instead by the
carrier mechanism, the receiving-party tracker status, or the value encoding.

Subtype rows come from the analysis engine (CookieDataset.sync_subtype_rows,
cached by scripts/annotate.py). See scripts/plot_scripts/sync_subtypes.py for how
the subtypes are derived.

Usage:
    python scripts/plot_scripts/plot_sync_subtypes_bar.py --data cookies_data --out plots/syncing --top 15 --by tier
"""

import argparse
import os
import sys
from collections import Counter, defaultdict

import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
import sync_subtypes as ss
from utils import apply_theme, save_figure, DARK


def plot_bar(data_dir: str, out_dir: str, top: int, by: str) -> None:
    apply_theme()
    events = ss.load_sync_events(data_dir)
    if by not in ss.DIMENSIONS:
        raise SystemExit(f"--by must be one of {list(ss.DIMENSIONS)}")
    order, colors = ss.DIMENSIONS[by]

    # Encoding only exists on confirmed rows; restrict to those so the bars mean
    # something (otherwise every candidate domain would be empty).
    rows = [e for e in events if ss.dim_value(e, by) is not None]
    if not rows:
        raise SystemExit(f"No events carry a '{by}' value.")

    # Rank receiving domains by total volume, keep top-N, fold the rest.
    dom_totals = Counter(e["to_domain"] for e in rows)
    keep = set(d for d, _ in dom_totals.most_common(top))
    domains = [d for d, _ in dom_totals.most_common(top)]

    # counts[domain][category]
    counts: dict[str, Counter] = defaultdict(Counter)
    all_counts: Counter = Counter()
    for e in rows:
        cat = ss.dim_value(e, by)
        all_counts[cat] += 1
        dom = e["to_domain"] if e["to_domain"] in keep else "(other)"
        counts[dom][cat] += 1

    # Bar order: ALL first, then top domains by volume; (other) appended if present.
    bar_labels = ["ALL"] + domains
    if any(d not in keep for d in dom_totals):
        bar_labels.append("(other)")
    bar_counts = [all_counts] + [counts[d] for d in bar_labels[1:]]

    # Stack categories in the vocabulary's canonical order (+ any stragglers).
    cats = [c for c in order if any(bc.get(c) for bc in bar_counts)]
    cats += sorted(
        {c for bc in bar_counts for c in bc if c not in order}
    )

    fig, ax = plt.subplots(figsize=(max(9, 1.0 * len(bar_labels) + 3), 7))
    x = range(len(bar_labels))
    bottom = [0] * len(bar_labels)
    for cat in cats:
        vals = [bc.get(cat, 0) for bc in bar_counts]
        ax.bar(
            x, vals, bottom=bottom, label=cat,
            color=colors.get(cat, DARK), edgecolor="white", linewidth=0.4, width=0.8,
        )
        bottom = [b + v for b, v in zip(bottom, vals)]

    ax.set_xticks(list(x))
    ax.set_xticklabels(bar_labels, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("sync rows (per-param)")
    ax.set_title(f"Cookie-Sync Subtype Composition by {by}", fontsize=17, fontweight="bold", pad=14)
    # Visual divider after the ALL aggregate bar.
    ax.axvline(0.5, color=DARK, linewidth=0.8, alpha=0.4, linestyle=":")
    ax.legend(title=by, fontsize=10, title_fontsize=11, loc="upper right")
    ax.margins(x=0.01)
    plt.tight_layout()
    save_figure(out_dir, f"plot_sync_subtypes_bar_{by}.png", f"plot_sync_subtypes_bar_{by}.pdf")

    ss.print_subtype_report(events)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--out", default="./plots/syncing")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--by", default="tier", choices=list(ss.DIMENSIONS))
    args = parser.parse_args()
    plot_bar(args.data, args.out, args.top, args.by)
