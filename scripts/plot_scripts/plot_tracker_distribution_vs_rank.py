
"""
Tracker Count Distribution vs. Website Rank — equal-width bins
==============================================================

A cleaner companion to ``plot_tracker_count_vs_rank.py``. That script bins by the
project's ``RANK_TIERS`` (Top 10 / Top 50 / Top 100 / 101–1k / …), which are very
uneven in both width and sample size, so the per-tier distribution panel is hard
to read. This script instead uses **equal bins**:

  * ``--bin-mode linear`` (default)   — equal-width bins in linear rank space, so
    each bin covers the same number of rank positions (e.g. 1–167k, 167k–333k, …).
  * ``--bin-mode logwidth``           — equal-width bins in log10(rank) space, i.e.
    one decade each (1–10, 10–100, 100–1k, …).
  * ``--bin-mode quantile``           — equal-count bins, so every bin holds the
    same number of sites (useful when you care about distribution shape rather
    than the literal rank ranges).

Three views of the *number of tracker cookies per site* across rank bins:

  1. ``violin``  — full distribution shape per bin (KDE clipped at 0), with the
                   median dot and IQR whisker drawn inside each violin.
  2. ``box``     — classic box-and-whisker per bin (median, IQR, 1.5×IQR whiskers)
                   with the mean marked.
  3. ``ribbon``  — median line across bins with a shaded IQR band; the clean,
                   un-confusing replacement for the original stacked median+IQR bar.

Data loading reuses :func:`load_site_tracker_counts` from
``plot_tracker_count_vs_rank.py`` so the tracker definition and rank source stay
identical across both scripts.

Usage:
    python3 scripts/plot_scripts/plot_tracker_distribution_vs_rank.py \\
        --data cookies_data [--rank list_websites_1M.csv] --out plots/trackers

    # only one view, more bins, equal-count binning:
    python3 scripts/plot_scripts/plot_tracker_distribution_vs_rank.py \\
        --data cookies_data --kind box --bins 12 --bin-mode quantile
"""

import argparse
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    save_figure,
    BG,
    DARK,
    MID,
    LIGHT,
    ACCENT,
    ACCENT2,
    COLORS,
)

# Reuse the exact site-level loader (tracker definition + rank source) from the
# sibling script so the two stay consistent.
from plot_tracker_count_vs_rank import load_site_tracker_counts

RANK_MIN, RANK_MAX = 1, 1_000_000


# ---------------------------------------------------------------------------
# Binning
# ---------------------------------------------------------------------------


def _fmt_rank(x: float) -> str:
    """Compact human label for a rank edge: 1, 10, 1k, 10k, 100k, 1M."""
    x = float(x)
    if x >= 1_000_000:
        return f"{x / 1_000_000:g}M"
    if x >= 1_000:
        return f"{x / 1_000:g}k"
    return f"{x:g}"


def _bin_edges(ranks: np.ndarray, bins: int, mode: str) -> np.ndarray:
    """Return ``bins + 1`` rank edges for the chosen binning mode."""
    if mode == "quantile":
        qs = np.linspace(0, 1, bins + 1)
        edges = np.quantile(ranks, qs)
        # Guard against duplicate edges when many sites share a rank.
        edges = np.unique(np.round(edges).astype(int)).astype(float)
        return edges
    if mode == "logwidth":
        # equal-width in log10 space across the rank universe.
        return np.logspace(np.log10(RANK_MIN), np.log10(RANK_MAX), bins + 1)
    # linear: equal-width in linear rank space.
    return np.linspace(RANK_MIN, RANK_MAX, bins + 1)


def bin_sites(matched: pd.DataFrame, bins: int, mode: str):
    """
    Group sites into equal bins and return per-bin distributions + summary stats.

    Returns a dict with parallel lists (one entry per non-empty bin):
        labels, data, median, q1, q3, mean, n
    """
    ranks = matched["rank"].clip(RANK_MIN, RANK_MAX).to_numpy()
    counts = matched["n_tracker"].to_numpy(dtype=float)
    edges = _bin_edges(ranks, bins, mode)

    # np.digitize: idx in 1..len(edges)-1 for in-range values.
    idx = np.clip(np.digitize(ranks, edges, right=True), 1, len(edges) - 1)

    out = {k: [] for k in ("labels", "data", "median", "q1", "q3", "mean", "n")}
    for b in range(1, len(edges)):
        sel = idx == b
        if not sel.any():
            continue
        vals = counts[sel]
        lo, hi = edges[b - 1], edges[b]
        out["labels"].append(f"{_fmt_rank(lo)}–{_fmt_rank(hi)}")
        out["data"].append(vals)
        out["median"].append(float(np.median(vals)))
        out["q1"].append(float(np.percentile(vals, 25)))
        out["q3"].append(float(np.percentile(vals, 75)))
        out["mean"].append(float(np.mean(vals)))
        out["n"].append(int(sel.sum()))
    return out


def _display_cap(stats: dict) -> float:
    """A sensible y-axis cap so a few heavy outliers don't flatten the plot."""
    all_counts = np.concatenate(stats["data"]) if stats["data"] else np.array([1.0])
    cap = np.percentile(all_counts, 97.5)
    cap = max(cap, max(stats["q3"]) + 1 if stats["q3"] else 1)
    return float(cap)


def _annotate_n(ax, stats, y, *, fontsize=8.5):
    """Write n=… (and med=…) above each bin position."""
    for i, (n, med) in enumerate(zip(stats["n"], stats["median"])):
        ax.text(
            i,
            y,
            f"med={med:.0f}\n(n={n:,})",
            ha="center",
            va="bottom",
            fontsize=fontsize,
            color=DARK,
        )


def _style_axis(ax, labels, ylabel, title, ymax):
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_xlabel("Website Rank (equal bins)", fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.set_title(title, fontsize=13, pad=10)
    ax.set_ylim(0, ymax)
    ax.grid(axis="y", alpha=0.32)
    ax.spines[["top", "right"]].set_visible(False)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def plot_violin(stats: dict, out_dir: str) -> None:
    apply_theme()
    fig, ax = plt.subplots(figsize=(11, 6))
    pos = np.arange(len(stats["labels"]))
    cap = _display_cap(stats)

    parts = ax.violinplot(
        stats["data"],
        positions=pos,
        widths=0.82,
        showmeans=False,
        showmedians=False,
        showextrema=False,
    )
    for i, body in enumerate(parts["bodies"]):
        body.set_facecolor(COLORS[i % len(COLORS)])
        body.set_edgecolor(DARK)
        body.set_linewidth(0.7)
        body.set_alpha(0.78)
        # Clip the KDE at 0 — tracker counts can't be negative.
        verts = body.get_paths()[0].vertices
        verts[:, 1] = np.clip(verts[:, 1], 0, None)

    # Inner median dot + IQR whisker (seaborn-style inner='box').
    for i in pos:
        ax.vlines(i, stats["q1"][i], stats["q3"][i], color=DARK, lw=4, alpha=0.55)
        ax.plot(i, stats["median"][i], "o", color=BG, mec=DARK, mew=1.2, ms=6, zorder=5)

    _annotate_n(ax, stats, y=cap * 0.9)
    _style_axis(
        ax,
        stats["labels"],
        "# Tracker Cookies per Site",
        "Tracker Count Distribution by Rank (violin)",
        cap * 1.04,
    )
    fig.suptitle(
        "Tracker Cookie Count vs. Website Popularity",
        fontsize=16,
        fontweight="bold",
        y=1.01,
    )
    plt.tight_layout()
    save_figure(
        out_dir,
        "plot_tracker_distribution_vs_rank_violin.png",
        "plot_tracker_distribution_vs_rank_violin.pdf",
    )


def plot_box(stats: dict, out_dir: str, show_fliers: bool = False) -> None:
    apply_theme()
    fig, ax = plt.subplots(figsize=(11, 6))
    pos = np.arange(len(stats["labels"]))
    cap = _display_cap(stats)

    bp = ax.boxplot(
        stats["data"],
        positions=pos,
        widths=0.6,
        patch_artist=True,
        showmeans=True,
        showfliers=show_fliers,
        medianprops=dict(color=DARK, linewidth=2),
        whiskerprops=dict(color=DARK, linewidth=1.1),
        capprops=dict(color=DARK, linewidth=1.1),
        flierprops=dict(
            marker="o", markerfacecolor=MID, markeredgecolor="none", markersize=2,
            alpha=0.25,
        ),
        meanprops=dict(
            marker="D", markerfacecolor=BG, markeredgecolor=ACCENT, markersize=6,
        ),
    )
    for i, box in enumerate(bp["boxes"]):
        box.set_facecolor(COLORS[i % len(COLORS)])
        box.set_edgecolor(DARK)
        box.set_alpha(0.82)
        box.set_linewidth(0.8)

    # Per-bin labels above each box's q3 (keeps the upper-left clear for the legend).
    for i, (q3, n, med) in enumerate(zip(stats["q3"], stats["n"], stats["median"])):
        ax.text(
            i, q3 + cap * 0.03, f"med={med:.0f}\n(n={n:,})",
            ha="center", va="bottom", fontsize=8.5, color=DARK,
        )
    _style_axis(
        ax,
        stats["labels"],
        "# Tracker Cookies per Site",
        "Tracker Count Distribution by Rank (box)",
        cap * 1.12,
    )
    # Legend entries for the mean/median markers; whisker rule in the legend title.
    ax.scatter([], [], marker="D", facecolor=BG, edgecolor=ACCENT, s=45, label="Mean")
    ax.plot([], [], color=DARK, lw=2, label="Median")
    note = "whiskers = 1.5×IQR" + ("" if show_fliers else "; outliers hidden")
    ax.legend(fontsize=9, loc="upper left", title=note, title_fontsize=8)
    fig.suptitle(
        "Tracker Cookie Count vs. Website Popularity",
        fontsize=16,
        fontweight="bold",
        y=1.01,
    )
    plt.tight_layout()
    save_figure(
        out_dir,
        "plot_tracker_distribution_vs_rank_box.png",
        "plot_tracker_distribution_vs_rank_box.pdf",
    )


def plot_ribbon(stats: dict, out_dir: str) -> None:
    apply_theme()
    fig, ax = plt.subplots(figsize=(11, 6))
    pos = np.arange(len(stats["labels"]))

    ax.fill_between(
        pos, stats["q1"], stats["q3"],
        color=ACCENT2, alpha=0.45, label="IQR (25th–75th %ile)", zorder=1,
    )
    ax.plot(
        pos, stats["median"], "-o", color=ACCENT, lw=2.2, ms=7,
        mec=BG, mew=1.2, label="Median", zorder=3,
    )
    ax.plot(
        pos, stats["mean"], "--", color=DARK, lw=1.6, alpha=0.8, label="Mean", zorder=2,
    )

    ymax = (max(stats["q3"]) if stats["q3"] else 1) * 1.30
    for i in pos:
        ax.text(
            i, stats["q3"][i] + ymax * 0.015,
            f"med={stats['median'][i]:.0f}\n(n={stats['n'][i]:,})",
            ha="center", va="bottom", fontsize=8.5, color=DARK,
        )
    _style_axis(
        ax,
        stats["labels"],
        "# Tracker Cookies (Median + IQR)",
        "Tracker Count Distribution by Rank (median + IQR)",
        ymax,
    )
    ax.legend(fontsize=9, loc="upper left")
    fig.suptitle(
        "Tracker Cookie Count vs. Website Popularity",
        fontsize=16,
        fontweight="bold",
        y=1.01,
    )
    plt.tight_layout()
    save_figure(
        out_dir,
        "plot_tracker_distribution_vs_rank_ribbon.png",
        "plot_tracker_distribution_vs_rank_ribbon.pdf",
    )


VIEWS = {"violin": plot_violin, "box": plot_box, "ribbon": plot_ribbon}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(data_dir, rank_csv, out_dir, kind, bins, bin_mode):
    print("Loading site cookie data…")
    df = load_site_tracker_counts(data_dir, rank_csv)
    if df.empty:
        print("No is_tracker data found. Re-collect with --tracker-lists.")
        return

    matched = df.dropna(subset=["rank"]).copy()
    matched["rank"] = matched["rank"].astype(int)
    matched = matched[(matched["rank"] >= RANK_MIN) & (matched["rank"] <= RANK_MAX)]
    print(
        f"  {len(df):,} sites total; {len(matched):,} matched to ranks "
        f"({len(df) - len(matched):,} unmatched/out-of-range)"
    )
    if matched.empty:
        print("No sites could be matched to a rank. Pass --rank or embed rank in crawl.")
        return

    stats = bin_sites(matched, bins, bin_mode)
    if not stats["labels"]:
        print("No populated bins.")
        return
    print(
        f"  {bin_mode} binning -> {len(stats['labels'])} bins: "
        + ", ".join(f"{lbl}(n={n:,})" for lbl, n in zip(stats["labels"], stats["n"]))
    )

    chosen = list(VIEWS) if kind == "all" else [kind]
    for k in chosen:
        VIEWS[k](stats, out_dir)
    print(f"\nDone. Saved {len(chosen)} view(s) to {out_dir}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Plot the distribution of tracker-cookie count per site across "
            "EQUAL rank bins — violin, box, or median+IQR ribbon."
        )
    )
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument(
        "--rank",
        default=None,
        help="Headerless rank CSV (rank,domain). Optional if rank is in crawl_context.",
    )
    parser.add_argument("--out", default="./plots/trackers")
    parser.add_argument(
        "--kind",
        default="all",
        choices=["all", "violin", "box", "ribbon"],
        help="Which view(s) to render (default: all).",
    )
    parser.add_argument(
        "--bins", type=int, default=6,
        help="Number of equal bins (default 6 = one decade each in logwidth mode).",
    )
    parser.add_argument(
        "--bin-mode",
        default="linear",
        choices=["linear", "logwidth", "quantile"],
        help="linear = equal rank-range per bin (default); logwidth = equal width in log10(rank); quantile = equal #sites per bin.",
    )
    args = parser.parse_args()
    main(args.data, args.rank, args.out, args.kind, args.bins, args.bin_mode)

