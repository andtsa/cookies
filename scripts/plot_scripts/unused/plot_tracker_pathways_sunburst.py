"""
Tracker Delivery Pathways — Sunburst (radial hierarchy) diagram

A reading-friendlier alternative to the alluvial flow diagram for the same
question — "what are the different ways trackers end up on a page?" — laid out
as concentric rings instead of crossing ribbons:

    ring 1 (innermost)  Party context     first-party / third-party / unknown
    ring 2              Setter mechanism  http / javascript / unknown
    ring 3 (outermost)  Delivery channel  Page load / Tracking pixel / Script tag /
                                           Background call / Beacon / Iframe / …

Each ring is a full circle of arcs; an arc's angular width is proportional to
the number of cookies that took that path, and it is nested radially inside
its parent arc from the previous ring — so you can read both "what fraction of
all cookies are third-party" (ring 1) and "of those, what fraction were set via
JS, and via which exact channel" (rings 2-3) at a glance, without the visual
clutter of crossing ribbons.

Arcs are colored by ring (party/mechanism/channel get progressively lighter
shades along the project's warm palette) and outlined in ``ACCENT`` when the
*majority* of cookies on that arc are tracker-list-flagged, so tracker-heavy
routes still visually pop out — addressing the same "which paths carry the
most tracking" question the alluvial version answered via ribbon color, just
encoded as an outline instead of competing with the arc's own hue.

Reads raw cookie records via ``CookieDataset.iter_raw_sites()`` for the same
reason as the alluvial version: ``setter_request_type`` (needed for the
delivery-channel ring) is not projected into the enriched ``cookies`` frame.
``party_type`` is recomputed with ``analysis.src.helpers.party_type`` so the
first/third-party split matches the rest of the dataset exactly.

Usage:
    python scripts/plot_scripts/plot_tracker_pathways_sunburst.py \
        --data cookies_data --country Netherlands --browser chromium \
        --out plots/pathways
"""

import argparse
import os
import sys
from collections import Counter, defaultdict

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Wedge, Patch

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

# --------------------------------------------------------------------- labels
PARTY_LABELS = {
    "first_party": "First-party",
    "third_party": "Third-party",
    "unknown": "Unknown party",
}
MECHANISM_LABELS = {
    "http": "HTTP (Set-Cookie)",
    "javascript": "JS write",
    "unknown": "Unknown",
}
_CHANNEL_BY_REQUEST_TYPE = {
    "Document": "Page load",
    "Image": "Tracking pixel",
    "Script": "Script tag",
    "Fetch": "Background call",
    "XHR": "Background call",
    "Ping": "Beacon",
    "SubDocument": "Iframe",
}

# Per-ring base hue, lightened progressively outward (innermost = strongest).
RING_COLORS = [DARK, ACCENT, ACCENT2]


def _channel(setter_type: str, request_type) -> str:
    if setter_type == "http":
        return _CHANNEL_BY_REQUEST_TYPE.get(request_type, "Other (HTTP)")
    if setter_type == "javascript":
        return "JS write"
    return "Unknown"


def _collect_flows(ds, country: str, browser: str):
    from analysis.src.helpers import party_type

    rows = []
    for site in ds.iter_raw_sites():
        if site.country != country or site.browser != browser:
            continue
        target_host = site.target_url.split("//")[-1].split("/")[0]
        for c in site.cookies:
            party = party_type(target_host, c.get("domain", ""))
            setter_type = c.get("setter_type", "unknown") or "unknown"
            channel = _channel(setter_type, c.get("setter_request_type"))
            rows.append(
                {
                    "party": party,
                    "mechanism": setter_type,
                    "channel": channel,
                    "is_tracker": bool(c.get("tracker_lists")),
                }
            )
    return rows


def _lighten(hex_color: str, amount: float) -> str:
    """Blend ``hex_color`` toward white by ``amount`` in [0, 1]."""
    import matplotlib.colors as mc

    r, g, b = mc.to_rgb(hex_color)
    return mc.to_hex((r + (1 - r) * amount, g + (1 - g) * amount, b + (1 - b) * amount))


def _draw_ring(ax, segments, r_inner, r_outer, base_color, total):
    """Draw one ring's worth of arcs.

    ``segments`` is an ordered list of ``(label, theta0, theta1, count, frac_tracker)``.
    Returns nothing; draws wedges + labels directly onto ``ax``.
    """
    thin_labels = []
    for label, t0, t1, count, frac_trk in segments:
        width = t1 - t0
        if width <= 0:
            continue
        # Shade by tracker share within this arc: more tracker-heavy -> darker/
        # warmer fill (toward ACCENT), outlined boldly when trackers are the majority.
        fill = _lighten(base_color, 0.55 * (1 - frac_trk))
        edge = ACCENT if frac_trk >= 0.5 else BG
        lw = 2.4 if frac_trk >= 0.5 else 1.0
        wedge = Wedge(
            (0, 0),
            r_outer,
            t0,
            t1,
            width=r_outer - r_inner,
            facecolor=fill,
            edgecolor=edge,
            linewidth=lw,
            zorder=2,
        )
        ax.add_patch(wedge)

        mid = np.deg2rad((t0 + t1) / 2)
        pct = count / total * 100
        text = f"{label}\n{count:,} ({pct:.0f}%)"

        if width >= 4:
            # Wide enough: label inline, rotated to follow the arc.
            r_txt = (r_inner + r_outer) / 2
            rotation = (t0 + t1) / 2
            if 90 < rotation < 270:
                rotation -= 180
            ax.text(
                r_txt * np.cos(mid),
                r_txt * np.sin(mid),
                text,
                ha="center",
                va="center",
                fontsize=8.5,
                fontweight="bold",
                color=DARK,
                rotation=rotation,
                rotation_mode="anchor",
                zorder=3,
            )
        else:
            # Too thin to label inline — defer to the global leader-line pass
            # below, which sorts ALL thin labels (across every ring) by angle
            # and assigns radial tiers so neighbours never collide, whether
            # they're adjacent slices of the same ring or stacked across rings.
            mid_deg = (t0 + t1) / 2.0
            thin_labels.append((mid_deg, r_outer, text))
    return thin_labels


def _place_thin_labels(ax, thin_labels, r_base):
    """Leader-line out every label too thin to fit inline.

    Sorted by angle, then assigned cyclically increasing radial tiers — so
    consecutive labels (by angle, regardless of which ring they came from)
    always land at different radii and never overlap each other or the rings.
    """
    if not thin_labels:
        return
    n_tiers = 4
    tier_step = 0.95
    ordered = sorted(thin_labels, key=lambda t: t[0])
    for i, (mid_deg, r_anchor, text) in enumerate(ordered):
        mid = np.deg2rad(mid_deg)
        cos_a, sin_a = np.cos(mid), np.sin(mid)
        r_label = r_base + 0.5 + tier_step * (i % n_tiers)
        ax.annotate(
            text,
            xy=(r_anchor * cos_a, r_anchor * sin_a),
            xytext=(r_label * cos_a, r_label * sin_a),
            ha="center",
            va="center",
            fontsize=7.5,
            fontweight="bold",
            color=DARK,
            zorder=3,
            arrowprops=dict(arrowstyle="-", color=DARK, lw=0.8, alpha=0.6),
        )


def _build_rings(rows, total):
    """Compute nested arc spans for all three rings, each child set spanning
    exactly its parent's angular range (so the hierarchy reads radially)."""
    # ring 1: party
    party_counts = Counter(r["party"] for r in rows)
    party_order = sorted(party_counts, key=lambda k: party_counts[k], reverse=True)

    ring1, ring2, ring3 = [], [], []
    angle = 0.0
    for party in party_order:
        prows = [r for r in rows if r["party"] == party]
        pcount = len(prows)
        pwidth = 360.0 * pcount / total
        ptrk = sum(r["is_tracker"] for r in prows) / pcount if pcount else 0.0
        ring1.append(
            (PARTY_LABELS.get(party, party), angle, angle + pwidth, pcount, ptrk)
        )

        # ring 2: mechanism, nested within [angle, angle+pwidth]
        mech_counts = Counter(r["mechanism"] for r in prows)
        mech_order = sorted(mech_counts, key=lambda k: mech_counts[k], reverse=True)
        a2 = angle
        for mech in mech_order:
            mrows = [r for r in prows if r["mechanism"] == mech]
            mcount = len(mrows)
            mwidth = pwidth * mcount / pcount
            mtrk = sum(r["is_tracker"] for r in mrows) / mcount if mcount else 0.0
            ring2.append(
                (MECHANISM_LABELS.get(mech, mech), a2, a2 + mwidth, mcount, mtrk)
            )

            # ring 3: channel, nested within [a2, a2+mwidth]
            chan_counts = Counter(r["channel"] for r in mrows)
            chan_order = sorted(chan_counts, key=lambda k: chan_counts[k], reverse=True)
            a3 = a2
            for chan in chan_order:
                crows = [r for r in mrows if r["channel"] == chan]
                ccount = len(crows)
                cwidth = mwidth * ccount / mcount
                ctrk = sum(r["is_tracker"] for r in crows) / ccount if ccount else 0.0
                ring3.append((chan, a3, a3 + cwidth, ccount, ctrk))
                a3 += cwidth
            a2 += mwidth
        angle += pwidth
    return ring1, ring2, ring3


def plot_tracker_pathways_sunburst(
    data_dir: str, country: str, browser: str, out_dir: str
) -> None:
    apply_theme()
    ds = dataset(data_dir)
    rows = _collect_flows(ds, country, browser)
    if not rows:
        print(f"No cookies found for {country}/{browser} in {data_dir!r}.")
        return

    total = len(rows)
    ring1, ring2, ring3 = _build_rings(rows, total)

    fig, ax = plt.subplots(figsize=(11, 11), subplot_kw={"aspect": "equal"})

    # Ring radii: a small hole in the middle, three equal-thickness annuli.
    r0, r1, r2, r3 = 1.0, 3.0, 5.0, 7.0
    thin = []
    thin += _draw_ring(ax, ring1, r0, r1, RING_COLORS[0], total)
    thin += _draw_ring(ax, ring2, r1, r2, RING_COLORS[1], total)
    thin += _draw_ring(ax, ring3, r2, r3, RING_COLORS[2], total)
    _place_thin_labels(ax, thin, r3)

    n_trackers = sum(r["is_tracker"] for r in rows)
    ax.text(
        0,
        0,
        f"{total:,}\ncookies",
        ha="center",
        va="center",
        fontsize=15,
        fontweight="bold",
        color=DARK,
    )

    ax.set_xlim(-7.2, 7.2)
    ax.set_ylim(-7.2, 7.2)
    ax.axis("off")

    # Ring legend (what each radial band represents).
    ring_handles = [
        Patch(
            facecolor=_lighten(RING_COLORS[0], 0.3),
            edgecolor=BG,
            label="Ring 1 — Party context",
        ),
        Patch(
            facecolor=_lighten(RING_COLORS[1], 0.3),
            edgecolor=BG,
            label="Ring 2 — Setter mechanism",
        ),
        Patch(
            facecolor=_lighten(RING_COLORS[2], 0.3),
            edgecolor=BG,
            label="Ring 3 — Delivery channel",
        ),
        Patch(
            facecolor=LIGHT,
            edgecolor=ACCENT,
            linewidth=2.4,
            label=f"Outline = majority tracker-flagged ({n_trackers:,}/{total:,} cookies overall)",
        ),
    ]
    ax.legend(
        handles=ring_handles,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.08),
        ncol=2,
        fontsize=9.5,
        frameon=False,
    )

    ax.set_title(
        f"How Trackers Land on a Page — {country} / {browser}\n"
        f"Party context → Setter mechanism → Delivery channel (innermost → outermost)",
        fontsize=15,
        fontweight="bold",
        pad=10,
    )
    plt.tight_layout()
    save_figure(
        out_dir,
        f"plot_tracker_pathways_sunburst_{country.lower()}_{browser}.png",
        f"plot_tracker_pathways_sunburst_{country.lower()}_{browser}.pdf",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--country", default="Netherlands")
    parser.add_argument("--browser", default="chromium")
    parser.add_argument("--out", default="./plots/pathways")
    args = parser.parse_args()
    plot_tracker_pathways_sunburst(args.data, args.country, args.browser, args.out)
