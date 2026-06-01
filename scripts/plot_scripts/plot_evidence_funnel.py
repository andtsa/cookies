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

Reads PROCESSED data (entropy + md5) for the first three stages and the
``cookie_syncing`` annotations for the last. The synced stage counts the
distinct cookies whose value was confirmed sent cross-domain.

Usage:
    python scripts/plot_scripts/plot_evidence_funnel.py \
        --processed cookies_data_processed --synced cookies_data/chromium --out plots/funnel
"""

import argparse
import glob
import hashlib
import json
import os
import sys

import matplotlib.pyplot as plt
import matplotlib.patheffects as pe

sys.path.insert(0, os.path.dirname(__file__))
from utils import apply_theme, save_figure, BG, DARK, LIGHT, ACCENT, ACCENT2, MID

HIGH_ENTROPY_BITS = 36.0


def _iter_json(data_dir: str):
    paths = sorted(glob.glob(os.path.join(data_dir, "**", "*.json"), recursive=True))
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                yield json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue


def _compute_stages(processed_dir: str, synced_dir: str):
    """Count evidence in a single consistent unit: the distinct cookie-value
    identity (name, md5_value).

    The four methodologies are *independent* axes of evidence, not strict nested
    subsets (a cookie can be synced without being shared across >=2 of the
    crawled sites). So each stage is reported as a fraction of *all* distinct
    values rather than "% of the previous stage", and the figure sorts the
    evidence stages by size so it always reads as a clean funnel without
    implying a containment that does not hold.
    """
    # key (name, md5) -> {"he": bool, "tracker": bool, "sites": set}
    keys: dict[tuple, dict] = {}

    for data in _iter_json(processed_dir):
        site = data.get("target_url", "")
        for c in data.get("cookies", []):
            name = c.get("name", "")
            md5 = c.get("md5_value", "")
            if not name or not md5:
                continue
            info = keys.setdefault(
                (name, md5), {"he": False, "tracker": False, "sites": set()}
            )
            if c.get("total_bits", 0.0) >= HIGH_ENTROPY_BITS:
                info["he"] = True
            if c.get("is_tracker"):
                info["tracker"] = True
            info["sites"].add(site)

    all_keys = set(keys)
    he_keys = {k for k in all_keys if keys[k]["he"]}
    he_tracker = sum(1 for k in he_keys if keys[k]["tracker"])
    shared_keys = {k for k in all_keys if len(keys[k]["sites"]) >= 2}

    # Synced: distinct cookie values confirmed sent cross-domain. The synced dir
    # is the raw crawl (no md5_value), so hash the value to match the processed
    # (name, md5) identity.
    synced_keys: set = set()
    has_sync_data = False
    for data in _iter_json(synced_dir):
        sync = data.get("cookie_syncing")
        if sync is None:
            continue
        has_sync_data = True
        name_to_md5 = {
            c.get("name"): hashlib.md5((c.get("value", "") or "").encode()).hexdigest()
            for c in data.get("cookies", [])
        }
        for ev in sync.get("confirmed", []):
            nm = ev.get("cookie_name")
            if nm in name_to_md5:
                synced_keys.add((nm, name_to_md5[nm]))
    # Keep only synced identities we actually saw as cookies.
    synced_keys &= all_keys

    return {
        "total": len(all_keys),
        "high_entropy": len(he_keys),
        "high_entropy_tracker": he_tracker,
        "high_entropy_nontracker": len(he_keys) - he_tracker,
        "shared": len(shared_keys),
        "synced": len(synced_keys) if has_sync_data else 0,
        "has_sync_data": has_sync_data,
    }


def plot_evidence_funnel(processed_dir: str, synced_dir: str, out_dir: str) -> None:
    apply_theme()
    s = _compute_stages(processed_dir, synced_dir)

    # Stage 1 is the universe; the three evidence stages are independent axes,
    # so sort them by size to render a clean funnel (each annotated as a % of
    # all distinct values, never "% of previous" — they are not nested subsets).
    evidence = [
        ("High-entropy value", s["high_entropy"], ACCENT2,
         (s["high_entropy_tracker"], s["high_entropy_nontracker"])),
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
            ax.barh(y, w_trk, left=left, height=0.62, color=ACCENT,
                    edgecolor=BG, linewidth=1.0, zorder=3)
            ax.barh(y, width - w_trk, left=left + w_trk, height=0.62, color=color,
                    edgecolor=BG, linewidth=1.0, zorder=3)
        elif value > 0:
            ax.barh(y, width, left=left, height=0.62, color=color,
                    edgecolor=BG, linewidth=1.0, zorder=3)

        pct = f"  ({value / total * 100:.1f}% of all)" if i > 0 else ""
        ax.text(0.5, y + 0.42, f"{label}", ha="center", va="bottom",
                fontsize=13, fontweight="bold", color=DARK)
        # Light outline so the count stays legible even over a dark, narrow bar.
        ax.text(0.5, y, f"{value:,}{pct}", ha="center", va="center",
                fontsize=12, color=DARK, zorder=4,
                path_effects=[pe.withStroke(linewidth=3.5, foreground=BG)])

    if not s["has_sync_data"]:
        ax.text(0.5, -0.25,
                "Synced stage = 0: no cookie_syncing annotations in --synced dir "
                "(needs a fresh Chromium crawl + find_cookie_syncing.py --annotate)",
                ha="center", va="center", fontsize=9, color=ACCENT, style="italic",
                transform=ax.get_xaxis_transform())

    # Legend for the high-entropy split.
    from matplotlib.patches import Patch
    ax.legend(
        handles=[
            Patch(facecolor=ACCENT, label="Known tracker"),
            Patch(facecolor=ACCENT2, label="High-entropy, not flagged"),
        ],
        loc="upper right", fontsize=10,
    )

    ax.set_xlim(0, 1)
    ax.set_ylim(-0.5, n - 0.3)
    ax.axis("off")
    ax.set_title("Tracking-Evidence Funnel", fontsize=18, fontweight="bold", pad=16)
    plt.tight_layout()
    save_figure(out_dir, "plot_evidence_funnel.png", "plot_evidence_funnel.pdf")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--processed", default="./cookies_data_processed")
    parser.add_argument("--synced", default="./cookies_data/chromium")
    parser.add_argument("--out", default="./plots/funnel")
    args = parser.parse_args()
    plot_evidence_funnel(args.processed, args.synced, args.out)
