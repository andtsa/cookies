"""
Tracker Delivery Pathways — Sankey / alluvial flow diagram

Shows the different routes by which cookies (and especially *tracker* cookies)
land on a page, as a three-stage flow:

    Party context  →  Setter mechanism  →  Delivery channel

  Party context     first-party / third-party / unknown — whether the cookie's
                    registered domain matches the crawled page's
                    (``analysis.src.helpers.party_type``).

  Setter mechanism  http (a ``Set-Cookie`` response header was observed) /
                    javascript (a ``document.cookie`` write was observed) /
                    unknown (neither path was captured) — raw ``setter_type``.

  Delivery channel  for HTTP-set cookies, a human-readable bucket of the CDP
                    resource type that carried the ``Set-Cookie`` header:
                      Document     -> "page load"     (set during navigation)
                      Image        -> "tracking pixel"
                      Script       -> "script tag"
                      Fetch / XHR  -> "background call"
                      Ping         -> "beacon"
                      SubDocument  -> "iframe"
                      anything else -> "other"
                    For javascript-set cookies there is no resource type (the
                    write isn't a network request), so they all flow into a
                    single "JS write" channel; setter-less cookies flow into
                    "unknown".

Ribbons are colored by whether the cookie is flagged by a tracker list
(``tracker_lists`` — EasyPrivacy / OpenCookieDB), so the routes that carry the
most genuine tracking traffic visually pop out from the routes that mostly
carry ordinary first-party cookies.

Reads raw cookie records directly via ``CookieDataset.iter_raw_sites()``
(filtered to ``--country``/``--browser``) rather than the enriched ``cookies``
frame: ``setter_request_type`` — the field that makes the delivery-channel
stage meaningful — isn't projected into that frame (only the coarser
``set_by_type``/``set_by_third_party``/etc. are). ``party_type`` is recomputed
with the *exact* helper the dataset itself uses
(``analysis.src.helpers.party_type``), so the first/third-party split here is
guaranteed identical to every other plot that reads ``cookies_df``.

Usage:
    python scripts/plot_scripts/plot_tracker_pathways_sankey.py \
        --data cookies_data --country Netherlands --browser chromium \
        --out plots/pathways
"""

import argparse
import os
import sys
from collections import Counter, defaultdict

import matplotlib.pyplot as plt
from matplotlib.path import Path
from matplotlib.patches import PathPatch, Patch

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
    "javascript": "JavaScript write",
    "unknown": "Unknown mechanism",
}

# CDP resource type -> human delivery-channel bucket (HTTP path only).
_CHANNEL_BY_REQUEST_TYPE = {
    "Document": "Page load",
    "Image": "Tracking pixel",
    "Script": "Script tag",
    "Fetch": "Background call",
    "XHR": "Background call",
    "Ping": "Beacon",
    "SubDocument": "Iframe",
}


def _channel(setter_type: str, request_type: str | None) -> str:
    if setter_type == "http":
        return _CHANNEL_BY_REQUEST_TYPE.get(request_type, "Other (HTTP)")
    if setter_type == "javascript":
        return "JS write"
    return "Unknown"


# ----------------------------------------------------------------- data prep
def _collect_flows(ds, country: str, browser: str):
    """Build the per-cookie ``(party, mechanism, channel, is_tracker)`` rows.

    Iterates raw site records (``RawAccess.iter_raw_sites``) rather than the
    enriched frame — see module docstring for why ``setter_request_type``
    requires the raw cookie dicts. ``party_type`` is recomputed with the same
    helper :meth:`FrameAccess._build_cookies` uses, so results match the
    dataset's own first/third-party split exactly.
    """
    from analysis.src.helpers import party_type, registered_domain

    rows = []
    for site in ds.iter_raw_sites():
        if site.country != country or site.browser != browser:
            continue
        target_url = site.target_url
        target_host = target_url.split("//")[-1].split("/")[0]
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


def _node_order(rows, key, label_map=None):
    """Distinct values of ``key`` across ``rows``, ranked by total count desc."""
    counts = Counter(r[key] for r in rows)
    order = sorted(counts, key=lambda k: counts[k], reverse=True)
    labels = [label_map.get(k, k) if label_map else k for k in order]
    return order, labels, counts


# -------------------------------------------------------------- ribbon drawing
def _ribbon_path(x0, x1, y0_top, y0_bot, y1_top, y1_bot):
    """A smooth s-curve filled ribbon between two vertical spans."""
    xm = (x0 + x1) / 2
    verts = [
        (x0, y0_top),
        (xm, y0_top),
        (xm, y1_top),
        (x1, y1_top),
        (x1, y1_bot),
        (xm, y1_bot),
        (xm, y0_bot),
        (x0, y0_bot),
        (x0, y0_top),
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
    return Path(verts, codes)


_NODE_GAP_FRAC = 0.18  # fraction of total height spent on inter-node gaps per stage


def _layout_nodes(order, counts, total):
    """Return ``{category: (y_bottom, y_top)}`` stacked top-to-bottom with gaps."""
    n = len(order)
    if n == 0:
        return {}
    gap = total * _NODE_GAP_FRAC / max(n - 1, 1) if n > 1 else 0.0
    usable = total * (1 - _NODE_GAP_FRAC)
    layout = {}
    y = total  # start at the top, stack downward
    for cat in order:
        h = usable * (counts[cat] / total)
        layout[cat] = (y - h, y)
        y -= h + gap
    return layout


def _draw_stage_nodes(ax, x, layout, labels_by_cat, counts, color, total):
    for cat, (y0, y1) in layout.items():
        ax.add_patch(
            plt.Rectangle(
                (x - 0.012, y0),
                0.024,
                y1 - y0,
                facecolor=color,
                edgecolor=BG,
                linewidth=1.2,
                zorder=4,
            )
        )
        ax.text(
            x,
            (y0 + y1) / 2,
            f"{labels_by_cat[cat]}\n{counts[cat]:,}  ({counts[cat] / total * 100:.0f}%)",
            ha="center",
            va="center",
            fontsize=9,
            fontweight="bold",
            color=DARK,
            zorder=5,
            bbox=dict(
                boxstyle="round,pad=0.25", facecolor=BG, edgecolor="none", alpha=0.85
            ),
        )


def _draw_flows(ax, x0, x1, layout0, layout1, rows, key0, key1, total):
    """Draw ribbons between two adjacent stages, colored by ``is_tracker``."""
    # Pairwise (cat0, cat1, is_tracker) -> count
    pair_counts: dict[tuple, int] = defaultdict(int)
    for r in rows:
        pair_counts[(r[key0], r[key1], r["is_tracker"])] += 1

    # Track how much of each node's vertical extent has been consumed so far,
    # processing destination/source nodes in their stage's display order so
    # ribbons stack cleanly without overlapping.
    out_used = {cat: layout0[cat][0] for cat in layout0}  # consume bottom-up
    in_used = {cat: layout1[cat][0] for cat in layout1}

    order1 = list(layout1.keys())
    order0 = list(layout0.keys())

    for cat0 in order0:
        for cat1 in order1:
            for is_trk, color, z in ((False, LIGHT, 1), (True, ACCENT, 2)):
                cnt = pair_counts.get((cat0, cat1, is_trk), 0)
                if cnt <= 0:
                    continue
                h0_total = layout0[cat0][1] - layout0[cat0][0]
                h1_total = layout1[cat1][1] - layout1[cat1][0]
                src_total = sum(
                    pair_counts.get((cat0, c1, t), 0)
                    for c1 in order1
                    for t in (False, True)
                )
                dst_total = sum(
                    pair_counts.get((c0, cat1, t), 0)
                    for c0 in order0
                    for t in (False, True)
                )
                h0 = h0_total * (cnt / src_total) if src_total else 0.0
                h1 = h1_total * (cnt / dst_total) if dst_total else 0.0

                y0_bot = out_used[cat0]
                y0_top = y0_bot + h0
                y1_bot = in_used[cat1]
                y1_top = y1_bot + h1

                path = _ribbon_path(x0, x1, y0_top, y0_bot, y1_top, y1_bot)
                ax.add_patch(
                    PathPatch(
                        path, facecolor=color, edgecolor="none", alpha=0.55, zorder=z
                    )
                )

                out_used[cat0] = y0_top
                in_used[cat1] = y1_top


def plot_tracker_pathways_sankey(
    data_dir: str, country: str, browser: str, out_dir: str
) -> None:
    apply_theme()
    ds = dataset(data_dir)
    rows = _collect_flows(ds, country, browser)

    if not rows:
        print(f"No cookies found for {country}/{browser} in {data_dir!r}.")
        return

    total = len(rows)

    party_order, party_labels, party_counts = _node_order(rows, "party", PARTY_LABELS)
    mech_order, mech_labels, mech_counts = _node_order(
        rows, "mechanism", MECHANISM_LABELS
    )
    chan_order, chan_labels, chan_counts = _node_order(rows, "channel")

    party_layout = _layout_nodes(party_order, party_counts, total)
    mech_layout = _layout_nodes(mech_order, mech_counts, total)
    chan_layout = _layout_nodes(chan_order, chan_counts, total)

    fig, ax = plt.subplots(figsize=(15, 8))

    xs = [0.08, 0.5, 0.92]
    _draw_flows(
        ax, xs[0], xs[1], party_layout, mech_layout, rows, "party", "mechanism", total
    )
    _draw_flows(
        ax, xs[1], xs[2], mech_layout, chan_layout, rows, "mechanism", "channel", total
    )

    _draw_stage_nodes(
        ax,
        xs[0],
        party_layout,
        dict(zip(party_order, party_labels)),
        party_counts,
        MID,
        total,
    )
    _draw_stage_nodes(
        ax,
        xs[1],
        mech_layout,
        dict(zip(mech_order, mech_labels)),
        mech_counts,
        MID,
        total,
    )
    _draw_stage_nodes(
        ax,
        xs[2],
        chan_layout,
        dict(zip(chan_order, chan_labels)),
        chan_counts,
        MID,
        total,
    )

    for x, label in zip(xs, ("Party context", "Setter mechanism", "Delivery channel")):
        ax.text(
            x,
            total * 1.02,
            label,
            ha="center",
            va="bottom",
            fontsize=13,
            fontweight="bold",
            color=DARK,
        )

    n_trackers = sum(1 for r in rows if r["is_tracker"])
    ax.legend(
        handles=[
            Patch(
                facecolor=ACCENT,
                alpha=0.55,
                label=f"Known tracker ({n_trackers:,} cookies)",
            ),
            Patch(
                facecolor=LIGHT,
                alpha=0.55,
                label=f"Not list-flagged ({total - n_trackers:,} cookies)",
            ),
        ],
        loc="lower center",
        bbox_to_anchor=(0.5, -0.06),
        ncol=2,
        fontsize=10,
        frameon=False,
    )

    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-total * 0.02, total * 1.08)
    ax.axis("off")
    ax.set_title(
        f"How Trackers Land on a Page — {country} / {browser}\n"
        f"({total:,} cookies observed across the crawl)",
        fontsize=17,
        fontweight="bold",
        pad=20,
    )
    plt.tight_layout()
    save_figure(
        out_dir,
        f"plot_tracker_pathways_sankey_{country.lower()}_{browser}.png",
        f"plot_tracker_pathways_sankey_{country.lower()}_{browser}.pdf",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--country", default="Netherlands")
    parser.add_argument("--browser", default="chromium")
    parser.add_argument("--out", default="./plots/pathways")
    args = parser.parse_args()
    plot_tracker_pathways_sankey(args.data, args.country, args.browser, args.out)
