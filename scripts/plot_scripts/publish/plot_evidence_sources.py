"""
Evidence Source Comparison — three-panel figure

  Top panel   — Classifier flow diagram (explainer)
      A visual walkthrough of how the classifier works: observed cookie →
      signal detection (four types) → confidence tier assigned →
      classified as tracker or not.

  Panel A — Signal reach (stacked horizontal bars)
      One bar per evidence signal, split by classifier tier
      (confirmed / probable / possible), sorted by total reach.
      A colour stripe on the left edge shows the signal type.

  Panel B — What blocklist-only detection would miss (horizontal bars)
      For each of *our* collected signals (cross-site sharing, cookie syncing,
      JS cross-domain reads, entropy/capability, third-party context), the bar
      shows how many cookies it flags that would have been MISSED had we only
      relied on external tracker lists (EasyPrivacy + OpenCookieDB).

      Lighter segment = also caught by a blocklist.
      Darker segment  = would be missed by blocklist-only detection.

Reads classified_cookies (via CookieDataset) which already has tracker_signals
as a list column — no raw-site iteration needed.

Usage:
    python scripts/plot_scripts/plot_evidence_sources.py
    python scripts/plot_scripts/plot_evidence_sources.py \\
        --data cookies_data --country Netherlands --browser chromium \\
        --out plots/evidence
"""

import argparse
import os
import sys

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

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

# ------------------------------------------------------------------ signal map
# Each entry: (display_label, match_fn, category)
# category: "list" | "capability" | "behavioural" | "compound"
_SIGNALS = [
    (
        "Flagged by EasyPrivacy blocklist",
        lambda s: s.startswith("list:")
        and s != "list:nan"
        and s != "list:OpenCookieDB",
        "list",
    ),
    ("Named in OpenCookieDB", lambda s: s in ("list:nan", "list:OpenCookieDB"), "list"),
    (
        "Looks like a unique ID (high entropy + long-lived)",
        lambda s: s == "capability:high_entropy+persistent",
        "capability",
    ),
    (
        "Set by a third-party domain",
        lambda s: s == "context:set_by_third_party",
        "capability",
    ),
    (
        "Third-party, long-lived, and looks like a unique ID",
        lambda s: s == "context:third_party+long_lived+capable",
        "capability",
    ),
    (
        "Same value observed across 4+ websites (identifier sharing)",
        lambda s: "identifier_shared_across" in s,
        "behavioural",
    ),
    (
        "Value forwarded to a third-party domain (cookie syncing)",
        lambda s: "cookie_syncing_confirmed" in s,
        "behavioural",
    ),
    (
        "Read by JavaScript across multiple domains",
        lambda s: "js_read_across" in s,
        "behavioural",
    ),
    (
        "Confirmed by blocklist, context, and statistics together",
        lambda s: s.startswith("corroborated:"),
        "compound",
    ),
]

CATEGORY_COLORS = {
    "list": "#3d7ab5",  # steel blue
    "capability": "#3a8c60",  # forest green
    "behavioural": "#7a5bb0",  # purple
    "compound": "#888888",  # neutral grey
}

CATEGORY_LABELS = {
    "list": "Blocklist-based",
    "capability": "Statistical analysis",
    "behavioural": "Observed behaviour",
    "compound": "Combined signals",
}

TIER_COLORS = {
    "confirmed": ACCENT,  # dark orange  (#ba4f19)
    "probable": ACCENT2,  # amber        (#ecb157)
    "possible": MID,  # muted rose   (#ae8775)
}

TIER_LABELS = {
    "confirmed": "Confirmed — direct evidence",
    "probable": "Probable — strong signals",
    "possible": "Possible — weak or few signals",
}

TIER_ORDER = ["confirmed", "probable", "possible"]

# Signals we collect ourselves — compared against blocklists in Panel B.
# Must match display labels in _SIGNALS exactly.
OUR_SIGNALS = {
    "Same value observed across 4+ websites (identifier sharing)",
    "Value forwarded to a third-party domain (cookie syncing)",
    "Read by JavaScript across multiple domains",
    "Looks like a unique ID (high entropy + long-lived)",
    "Set by a third-party domain",
    "Third-party, long-lived, and looks like a unique ID",
}


def _is_list_signal(sig: str) -> bool:
    return sig.startswith("list:")


def _collect(cc):
    """For each defined signal, count total cookies + tier breakdown + list-only overlap."""
    results = []
    list_mask = cc["tracker_signals"].apply(
        lambda sigs: any(_is_list_signal(s) for s in sigs)
    )

    for label, match_fn, category in _SIGNALS:
        has_sig = cc["tracker_signals"].apply(
            lambda sigs: any(match_fn(s) for s in sigs)
        )
        sub = cc[has_sig]
        tier_counts = {t: int((sub["tracker_tier"] == t).sum()) for t in TIER_ORDER}
        total = len(sub)
        exclusive = int((has_sig & ~list_mask).sum())
        also_list = total - exclusive
        results.append(
            {
                "label": label,
                "category": category,
                "total": total,
                "tiers": tier_counts,
                "exclusive": exclusive,
                "also_list": also_list,
            }
        )

    results.sort(key=lambda r: r["total"], reverse=True)
    return results


def _draw_explainer(ax):
    """Top-panel flow diagram: cookie → signals → tier → classification."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    T = ax.transAxes

    def tbox(cx, cy, text, fc, tc, fs=8.0):
        ax.text(
            cx,
            cy,
            text,
            ha="center",
            va="center",
            fontsize=fs,
            color=tc,
            fontweight="bold",
            transform=T,
            zorder=4,
            bbox=dict(
                boxstyle="round,pad=0.4", facecolor=fc, edgecolor="none", alpha=0.93
            ),
        )

    def arrow(x0, x1, y):
        ax.annotate(
            "",
            xy=(x1, y),
            xytext=(x0, y),
            xycoords=T,
            textcoords=T,
            arrowprops=dict(arrowstyle="-|>", color=DARK, lw=1.4, mutation_scale=13),
        )

    def slim_arrow(x0, y0, x1, y1):
        ax.annotate(
            "",
            xy=(x1, y1),
            xytext=(x0, y0),
            xycoords=T,
            textcoords=T,
            arrowprops=dict(
                arrowstyle="-|>", color=DARK, lw=0.7, mutation_scale=9, alpha=0.45
            ),
        )

    def stage_label(cx, text):
        ax.text(
            cx,
            0.97,
            text,
            ha="center",
            va="top",
            fontsize=8.5,
            color=DARK,
            transform=T,
            style="italic",
            fontweight="bold",
        )

    # Station 1: observed cookie
    tbox(0.05, 0.50, "Observed\ncookie", DARK, BG, fs=9)
    arrow(0.108, 0.148, 0.50)

    # Station 2: signal types
    stage_label(0.27, "Signal detection")
    sig_entries = [
        ("Blocklist matching\n(EasyPrivacy, OCDB)", CATEGORY_COLORS["list"], BG),
        ("Statistical analysis\n(entropy, context)", CATEGORY_COLORS["capability"], BG),
        ("Behavioural signals\n(syncing, sharing)", CATEGORY_COLORS["behavioural"], BG),
        ("Combined signals\n(multiple agree)", CATEGORY_COLORS["compound"], BG),
    ]
    ys_sig = np.linspace(0.78, 0.22, len(sig_entries))
    for (lbl, fc, tc), y in zip(sig_entries, ys_sig):
        tbox(0.27, y, lbl, fc, tc, fs=7.5)
        slim_arrow(0.355, y, 0.408, 0.50)

    arrow(0.412, 0.440, 0.50)

    # Station 3: confidence tiers
    stage_label(0.545, "Confidence tier assigned")
    tier_entries = [
        ("Confirmed\nDirect evidence", TIER_COLORS["confirmed"], BG),
        ("Probable\nStrong signals", TIER_COLORS["probable"], DARK),
        ("Possible\nWeak or few signals", TIER_COLORS["possible"], DARK),
    ]
    ys_tier = np.linspace(0.72, 0.28, len(tier_entries))
    for (lbl, fc, tc), y in zip(tier_entries, ys_tier):
        tbox(0.545, y, lbl, fc, tc, fs=7.5)

    slim_arrow(0.612, ys_tier[0], 0.662, 0.67)
    slim_arrow(0.612, ys_tier[1], 0.662, 0.67)
    slim_arrow(0.612, ys_tier[2], 0.662, 0.30)

    # Station 4: outcomes
    stage_label(0.77, "Classification")
    tbox(0.77, 0.67, "Classified\nas tracker", ACCENT, BG, fs=9)
    tbox(0.77, 0.30, "Not a tracker", LIGHT, DARK, fs=9)

    ax.text(
        0.622,
        0.685,
        "tier ≥ Probable →",
        ha="left",
        va="center",
        fontsize=7,
        color=DARK,
        transform=T,
        style="italic",
    )
    ax.text(
        0.622,
        0.285,
        "tier = Possible\nor no signal →",
        ha="left",
        va="center",
        fontsize=7,
        color=DARK,
        transform=T,
        style="italic",
    )

    ax.set_title(
        "How the cookie tracker classifier works",
        fontsize=11,
        fontweight="bold",
        color=DARK,
        pad=6,
        loc="left",
    )


def plot_evidence_sources(
    data_dir: str, country: str | None, browser: str | None, out_dir: str
) -> None:
    apply_theme()
    ds_obj = dataset(data_dir)
    cc = ds_obj.classified_cookies

    if country and browser:
        cc = cc[(cc["country"] == country) & (cc["browser"] == browser)]

    if cc.empty:
        print("No classified cookies found.")
        return

    scope = f"{country} / {browser}" if country and browser else "all crawls"
    total_cookies = len(cc)
    results = _collect(cc)

    labels = [r["label"] for r in results]
    totals = [r["total"] for r in results]
    n = len(results)
    max_val = max(totals) or 1

    h_data = max(5, n * 0.62 + 2.0)
    h_expl = 3.5
    fig = plt.figure(figsize=(16, h_data + h_expl))
    gs = fig.add_gridspec(
        2,
        2,
        height_ratios=[h_expl, h_data],
        hspace=0.45,
        wspace=0.55,
    )
    ax_expl = fig.add_subplot(gs[0, :])
    ax_a = fig.add_subplot(gs[1, 0])
    ax_b = fig.add_subplot(gs[1, 1])

    _draw_explainer(ax_expl)

    # ---------------------------------------------------------------- Panel A
    bar_h = 0.58
    for i, r in enumerate(results):
        y = n - 1 - i
        x = 0
        for tier in TIER_ORDER:
            cnt = r["tiers"][tier]
            if cnt > 0:
                ax_a.barh(
                    y,
                    cnt,
                    left=x,
                    height=bar_h,
                    color=TIER_COLORS[tier],
                    edgecolor=BG,
                    linewidth=0.5,
                    zorder=2,
                )
                x += cnt
        ax_a.barh(
            y,
            max_val * 0.012,
            left=-max_val * 0.025,
            height=bar_h,
            color=CATEGORY_COLORS[r["category"]],
            edgecolor="none",
            zorder=3,
        )
        if r["total"] > 0:
            ax_a.text(
                r["total"] + max_val * 0.015,
                y,
                f"{r['total']:,}",
                va="center",
                fontsize=9,
                color=DARK,
            )

    ax_a.set_yticks(range(n))
    ax_a.set_yticklabels(reversed(labels), fontsize=9.5, color=DARK)
    ax_a.set_xlim(-max_val * 0.04, max_val * 1.18)
    ax_a.set_ylim(-0.6, n - 0.4)
    ax_a.set_xlabel("Number of cookies with this signal", fontsize=10, color=DARK)
    ax_a.set_axisbelow(True)
    ax_a.xaxis.grid(True, color=LIGHT, linewidth=0.8)
    ax_a.spines[["top", "right"]].set_visible(False)
    ax_a.spines[["left", "bottom"]].set_color(LIGHT)
    ax_a.tick_params(length=0)
    ax_a.set_title(
        "[A]  How many cookies does each signal flag?",
        fontsize=11,
        fontweight="bold",
        color=DARK,
        pad=10,
        loc="left",
    )

    cat_handles = [
        mpatches.Patch(color=CATEGORY_COLORS[c], label=CATEGORY_LABELS[c])
        for c in ["list", "capability", "behavioural", "compound"]
    ]
    tier_handles = [
        mpatches.Patch(color=TIER_COLORS[t], label=TIER_LABELS[t]) for t in TIER_ORDER
    ]
    ax_a.legend(
        handles=tier_handles + cat_handles,
        loc="lower right",
        fontsize=8.5,
        frameon=True,
        ncol=2,
        title="Confidence tier / signal type",
        title_fontsize=8.5,
    )

    # ---------------------------------------------------------------- Panel B
    our = [r for r in results if r["label"] in OUR_SIGNALS]
    our_labels = [r["label"] for r in our]
    m = len(our)
    max_our = max((r["total"] for r in our), default=1) or 1

    for i, r in enumerate(our):
        y = m - 1 - i
        excl = r["exclusive"]
        also = r["also_list"]

        if also > 0:
            ax_b.barh(
                y,
                also,
                height=bar_h,
                color=ACCENT2,
                edgecolor=BG,
                linewidth=0.5,
                zorder=2,
                label="Also caught by a blocklist" if i == 0 else "",
            )
        if excl > 0:
            ax_b.barh(
                y,
                excl,
                left=also,
                height=bar_h,
                color=ACCENT,
                edgecolor=BG,
                linewidth=0.5,
                zorder=2,
                label="Would be missed by blocklist-only detection" if i == 0 else "",
            )
        if excl > 0 and also > 0:
            ax_b.plot(
                [also, also],
                [y - bar_h / 2, y + bar_h / 2],
                color=DARK,
                linewidth=1.2,
                linestyle=":",
                zorder=3,
            )
        if r["total"] > 0:
            ax_b.text(
                r["total"] + max_our * 0.02,
                y,
                f"{excl:,} exclusive  /  {r['total']:,} total",
                va="center",
                fontsize=8.5,
                color=DARK,
            )

    ax_b.set_yticks(range(m))
    ax_b.set_yticklabels(reversed(our_labels), fontsize=9.5, color=DARK)
    ax_b.set_xlim(0, max_our * 1.6)
    ax_b.set_ylim(-0.6, m - 0.4)
    ax_b.set_xlabel("Cookies flagged", fontsize=10, color=DARK)
    ax_b.set_axisbelow(True)
    ax_b.xaxis.grid(True, color=LIGHT, linewidth=0.8)
    ax_b.spines[["top", "right"]].set_visible(False)
    ax_b.spines[["left", "bottom"]].set_color(LIGHT)
    ax_b.tick_params(length=0)
    ax_b.set_title(
        "[B]  How many would blocklist-only detection miss?",
        fontsize=11,
        fontweight="bold",
        color=DARK,
        pad=10,
        loc="left",
    )
    ax_b.legend(loc="lower right", fontsize=8.5, frameon=True)

    fig.suptitle(
        f"Cookie Tracker Detection — Evidence Sources  |  {scope}  ({total_cookies:,} cookies)",
        fontsize=14,
        fontweight="bold",
        color=DARK,
        y=1.005,
    )
    plt.tight_layout()
    slug = f"_{country.lower()}_{browser}" if country and browser else "_all"
    fname = f"plot_evidence_sources{slug}"
    save_figure(out_dir, f"{fname}.png", f"{fname}.pdf")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--country", default=None)
    parser.add_argument("--browser", default=None)
    parser.add_argument("--out", default="./plots/evidence")
    args = parser.parse_args()
    plot_evidence_sources(args.data, args.country, args.browser, args.out)
