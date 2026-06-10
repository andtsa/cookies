"""
Shared loader + console reporter for cookie-syncing *subtype* plots.

The per-param-row subtype dimensions are now computed by the analysis engine
(:meth:`analysis.CookieDataset.sync_subtype_rows`, cached on disk by
``annotate.py``); this module is a thin presentation layer over them — it owns
only the ordered subtype *vocabularies*, the on-theme *colors*, and the console
report. The dimensions, at per-param-row granularity:

  * tier      — the confidence ladder, with the URL/param-name regex layer folded
                in:  ``confirmed`` (cookie-value match)  >  ``endpoint-named`` (a
                high-entropy candidate row that ALSO landed on a known sync
                endpoint / ID-named param)  >  ``candidate`` (high-entropy only).
  * carrier   — the mechanism the identifier rode on, from the request's Chromium
                resource ``type``:  pixel / beacon / script / xhr-fetch /
                redirect-navigation / other.
  * tracker   — whether the receiving request matched a known tracker
                (EasyPrivacy), i.e. ``easyprivacy.matched``.
  * encoding  — confirmed rows only: how the value was transformed to match a
                cookie:  raw / url-encoded / base64 / substring.

This module is imported by the three plot scripts (plot_sync_sankey.py,
plot_sync_subtypes_bar.py, plot_sync_heatmap.py); it is not a CLI itself.
"""

from __future__ import annotations

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))  # scripts/plot_scripts (for utils)

import utils  # noqa: E402

# ---------------------------------------------------------------------------
# Subtype vocabularies (ordered) + on-theme colors
# ---------------------------------------------------------------------------

TIERS = ["confirmed", "endpoint-named", "candidate"]
CARRIERS = ["pixel", "beacon", "script", "xhr/fetch", "redirect/navigation", "other"]
ENCODINGS = ["raw", "url-encoded", "base64", "substring"]
TRACKER_LABELS = ["tracker", "non-tracker"]

# Stable color per category, drawn from the shared palette so every plot agrees.
_C = utils.COLORS


def _color_map(categories: list[str]) -> dict[str, str]:
    return {cat: _C[i % len(_C)] for i, cat in enumerate(categories)}


TIER_COLORS = {
    "confirmed": utils.ACCENT,  # strongest -> primary highlight
    "endpoint-named": utils.ACCENT2,  # promoted middle tier
    "candidate": utils.MID,  # weakest
}
CARRIER_COLORS = _color_map(CARRIERS)
ENCODING_COLORS = _color_map(ENCODINGS)
TRACKER_COLORS = {"tracker": utils.ACCENT, "non-tracker": utils.LIGHT}

# Which vocabulary + color map backs each dimension name.
DIMENSIONS = {
    "tier": (TIERS, TIER_COLORS),
    "carrier": (CARRIERS, CARRIER_COLORS),
    "encoding": (ENCODINGS, ENCODING_COLORS),
    "tracker": (TRACKER_LABELS, TRACKER_COLORS),
}


# ---------------------------------------------------------------------------
# Loading (delegates to the engine)
# ---------------------------------------------------------------------------


def load_sync_events(data_dir: str) -> list[dict]:
    """Return one event dict per confirmed/candidate **param row**.

    Each event: ``{from_domain, to_domain, carrier, tracker, tier, encoding}``
    (plus ``country``/``browser``) where ``tracker`` is a bool and ``encoding``
    is set on confirmed rows only (``None`` otherwise). Sourced from the engine's
    on-disk-cached :meth:`CookieDataset.sync_subtype_rows`.
    """
    return utils.dataset(data_dir).sync_subtype_rows()


# ---------------------------------------------------------------------------
# Helpers shared by the plot scripts
# ---------------------------------------------------------------------------


def dim_value(event: dict, dimension: str) -> str | None:
    """Return the categorical label of ``event`` along ``dimension``."""
    if dimension == "tracker":
        return "tracker" if event["tracker"] else "non-tracker"
    return event.get(dimension)


def topn_with_other(
    counter: Counter, n: int, other_label: str = "(other)"
) -> list[str]:
    """Top-``n`` keys by count, with the remainder folded into ``other_label``."""
    top = [k for k, _ in counter.most_common(n)]
    if len(counter) > n:
        top.append(other_label)
    return top


def fold_other(domain: str, keep: set[str], other_label: str = "(other)") -> str:
    return domain if domain in keep else other_label


# ---------------------------------------------------------------------------
# Console report (every plot script calls this on finish)
# ---------------------------------------------------------------------------


def print_subtype_report(events: list[dict]) -> None:
    total = len(events)
    print(f"\n{'=' * 70}")
    print("  Cookie-Sync Subtype Breakdown")
    print(f"  Total sync rows (per-param) : {total}")
    print(f"{'=' * 70}")
    if not total:
        print("  (no events)\n")
        return

    for dim, (order, _colors) in DIMENSIONS.items():
        # None values (e.g. encoding on candidate rows) don't belong to the dim.
        counts = Counter(v for e in events if (v := dim_value(e, dim)) is not None)
        # encoding only applies to confirmed rows; its denominator is those rows.
        denom = sum(counts.values())
        print(
            f"\n  By {dim}:" + (" (confirmed rows only)" if dim == "encoding" else "")
        )
        seen = set()
        for label in order + sorted(k for k in counts if k not in order):
            if label in seen:
                continue
            seen.add(label)
            c = counts.get(label)
            if not c:
                continue
            pct = 100.0 * c / denom if denom else 0.0
            bar = "#" * int(round(pct / 5))
            print(f"    {label:<22} {c:>7}  {pct:5.1f}%  {bar}")
    print()
