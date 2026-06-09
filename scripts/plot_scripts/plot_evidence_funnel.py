"""
Tracking-Evidence Funnel (headline figure)
Shows how the cookie population narrows as progressively stronger tracking
evidence is required — tying all four methodologies into one story:

    All cookies
      → High-entropy values   (uniqueness analysis;  total_bits ≥ cutoff)
      → Shared cross-site      (cross-site ID persistence)
      → Synced cross-domain    (cookie syncing)

Each stage is a tapering bar annotated with its count and % of the previous
stage. The high-entropy stage is split into tracker vs non-tracker to show the
entropy signal aligns with known trackers.


Usage:
    python scripts/plot_scripts/plot_evidence_funnel.py \
        --data cookies_data --out plots/funnel
"""

import argparse
import os
import sys

import matplotlib.pyplot as plt
import matplotlib.patheffects as pe

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


def _distinct_keys(df, mask=None):
    """Distinct ``(name, md5_value)`` cookie-value identities, optionally masked."""
    sub = df if mask is None else df[mask]
    return set(zip(sub["name"], sub["md5_value"]))


def _signal_fired(signals_col, substring, *, exact=False):
    if exact:
        return signals_col.apply(lambda sigs: substring in sigs)
    return signals_col.apply(lambda sigs: any(substring in s for s in sigs))


def _compute_stages(ds):
    """Count evidence in a single consistent unit: the distinct cookie-value
    identity (name, md5_value).

    The four methodologies are *independent* axes of evidence, not strict nested
    subsets (a cookie can be synced without being shared across >=2 of the
    crawled sites). So each stage is reported as a fraction of *all* distinct
    values rather than "% of the previous stage", and the figure sorts the
    evidence stages by size so it always reads as a clean funnel without
    implying a containment that does not hold.
    """
    classified = ds.classified_cookies
    if classified.empty:
        return {
            "total": 0,
            "high_entropy": 0,
            "high_entropy_tracker": 0,
            "high_entropy_nontracker": 0,
            "shared": 0,
            "synced": 0,
        }

    all_keys = _distinct_keys(classified)

    he_mask = classified["total_bits"] >= ds.high_entropy_bits
    he_keys = _distinct_keys(classified, he_mask)
    he_tracker_keys = _distinct_keys(classified, he_mask & classified["is_tracker"])

    signals = classified["tracker_signals"]
    shared_keys = _distinct_keys(
        classified, _signal_fired(signals, "identifier_shared_across")
    )
    synced_keys = _distinct_keys(
        classified,
        _signal_fired(signals, "behaviour:cookie_syncing_confirmed", exact=True),
    )

    return {
        "total": len(all_keys),
        "high_entropy": len(he_keys),
        "high_entropy_tracker": len(he_tracker_keys),
        "high_entropy_nontracker": len(he_keys) - len(he_tracker_keys),
        "shared": len(shared_keys),
        "synced": len(synced_keys),
    }


def plot_evidence_funnel(data_dir: str, out_dir: str) -> None:
    apply_theme()
    ds = dataset(data_dir)
    s = _compute_stages(ds)

    # Stage 1 is the universe; the three evidence stages are independent axes,
    # so sort them by size to render a clean funnel (each annotated as a % of
    # all distinct values, never "% of previous" — they are not nested subsets).
    evidence = [
        (
            "High-entropy value",
            s["high_entropy"],
            ACCENT2,
            (s["high_entropy_tracker"], s["high_entropy_nontracker"]),
        ),
        ("Synced cross-domain", s["synced"], DARK, None),
        ("Shared cross-site", s["shared"], ACCENT, None),
    ]
    evidence.sort(key=lambda x: x[1], reverse=True)
    stages = [("All cookie values", s["total"], MID, None)] + evidence

    fig, ax = plt.subplots(figsize=(11, 7))
    total = max(s["total"], 1)
    n = len(stages)
    min_vis = 0.012  # floor so tiny non-zero stages stay visible

    for i, (label, value, color, split) in enumerate(stages):
        # Centered tapering bar, width = fraction of all distinct values.
        width = max(value / total, min_vis) if value > 0 else 0.0
        left = (1 - width) / 2
        y = n - 1 - i

        if split and value > 0:
            # Tracker / non-tracker split within the high-entropy bar.
            trk, _non = split
            w_trk = width * (trk / value)
            ax.barh(
                y,
                w_trk,
                left=left,
                height=0.62,
                color=ACCENT,
                edgecolor=BG,
                linewidth=1.0,
                zorder=3,
            )
            ax.barh(
                y,
                width - w_trk,
                left=left + w_trk,
                height=0.62,
                color=color,
                edgecolor=BG,
                linewidth=1.0,
                zorder=3,
            )
        elif value > 0:
            ax.barh(
                y,
                width,
                left=left,
                height=0.62,
                color=color,
                edgecolor=BG,
                linewidth=1.0,
                zorder=3,
            )

        pct = f"  ({value / total * 100:.1f}% of all)" if i > 0 else ""
        ax.text(
            0.5,
            y + 0.42,
            f"{label}",
            ha="center",
            va="bottom",
            fontsize=13,
            fontweight="bold",
            color=DARK,
        )
        # Light outline so the count stays legible even over a dark, narrow bar.
        ax.text(
            0.5,
            y,
            f"{value:,}{pct}",
            ha="center",
            va="center",
            fontsize=12,
            color=DARK,
            zorder=4,
            path_effects=[pe.withStroke(linewidth=3.5, foreground=BG)],
        )

    # Legend for the high-entropy split.
    from matplotlib.patches import Patch

    ax.legend(
        handles=[
            Patch(facecolor=ACCENT, label="Known tracker"),
            Patch(facecolor=ACCENT2, label="High-entropy, not flagged"),
        ],
        loc="upper right",
        fontsize=10,
    )

    ax.set_xlim(0, 1)
    ax.set_ylim(-0.5, n - 0.3)
    ax.axis("off")
    ax.set_title("Tracking-Evidence Funnel", fontsize=18, fontweight="bold", pad=16)
    plt.tight_layout()
    save_figure(out_dir, "plot_evidence_funnel.png", "plot_evidence_funnel.pdf")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--out", default="./plots/funnel")
    args = parser.parse_args()
    plot_evidence_funnel(args.data, args.out)
