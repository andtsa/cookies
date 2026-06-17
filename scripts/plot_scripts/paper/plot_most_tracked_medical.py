"""
Most-tracked medical / health websites
======================================

Ranks the *health sites themselves* by how heavily tracked they are — distinct
from ``plot_top_trackers_medical.py``, which ranks tracker **providers** across
health sites. For every health domain in the crawl (filtered to one
country/browser) we count:

    n_tracker    – number of tracker cookies observed (is_tracker rows)
    n_providers  – distinct tracker providers (tracker_provider)
    n_total      – all cookies (tracker + non-tracker), for context

and show the top N. Several interchangeable views are provided so you can pick
the one that reads best:

    bar       – horizontal ranking bars (warm value-gradient). The classic.
    lollipop  – same ranking as stems + dots; lighter, less ink.
    stacked   – tracker vs. other cookies stacked per site (tracker count in the
                context of the site's total cookie load).
    bubble    – total cookies (x) vs. distinct trackers (y), bubble size = tracker
                cookies; surfaces the outliers rather than a strict ranking.

Health list: the repo's health website CSV (``domain`` or ``rank,url`` columns).
Tracker definition and rank source come straight from the analysis engine
(``CookieDataset.classified_cookies``), identical to the other plot scripts.

Usage:
    python3 scripts/plot_scripts/plot_most_tracked_medical.py \\
        --data cookies_data --health health_websites_1K.csv --out plots/medical

    python3 scripts/plot_scripts/plot_most_tracked_medical.py \\
        --data cookies_data --kind bubble --top-n 20 --rank-by providers
"""

import argparse
import csv
import os
import sys

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))

from utils import (  # noqa: E402
    apply_theme,
    save_figure,
    dataset,
    gradient_colors,
    BG,
    COLORS,
    ACCENT,
    ACCENT2,
    DARK,
    MID,
    LIGHT,
)

try:
    import tldextract  # the repo already depends on this
except Exception:  # pragma: no cover - fallback if unavailable
    tldextract = None


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def _registered_domain(value: str) -> str:
    """Best-effort registrable domain from a domain or URL string."""
    v = (value or "").strip().lower()
    if not v:
        return ""
    if tldextract is not None:
        ext = tldextract.extract(v)
        return ".".join(p for p in (ext.domain, ext.suffix) if p)
    # crude fallback: strip scheme/path, keep last two labels
    v = v.split("//")[-1].split("/")[0].lstrip(".")
    parts = v.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else v


def load_health_domains(csv_path: str) -> set[str]:
    """Read the health list, accepting either a ``domain`` or ``url`` column."""
    domains: set[str] = set()
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        field = "domain" if "domain" in (reader.fieldnames or []) else "url"
        for row in reader:
            dom = _registered_domain(row.get(field, ""))
            if dom:
                domains.add(dom)
    return domains


def site_tracking_table(data_dir, health_csv, country, browser):
    """Per-health-site tracker counts for the given country/browser."""
    health = load_health_domains(health_csv)
    print(f"Loaded {len(health):,} health domains")

    ds = dataset(data_dir)
    cookies = ds.classified_cookies
    mask = (
        (cookies["country"] == country)
        & (cookies["browser"] == browser)
        & (cookies["registered_domain"].isin(health))
    )
    sub = cookies[mask].copy()
    if sub.empty:
        return sub  # empty frame signals "nothing matched"

    trk = sub[sub["is_tracker"]]
    g_total = sub.groupby("registered_domain").size().rename("n_total")
    g_trk = trk.groupby("registered_domain").size().rename("n_tracker")
    g_prov = (
        trk.groupby("registered_domain")["tracker_provider"].nunique().rename("n_providers")
    )
    out = (
        g_total.to_frame()
        .join(g_trk, how="left")
        .join(g_prov, how="left")
        .fillna(0)
        .reset_index()
        .rename(columns={"registered_domain": "site"})
    )
    out[["n_tracker", "n_providers"]] = out[["n_tracker", "n_providers"]].astype(int)
    out["pct_tracker"] = np.where(
        out["n_total"] > 0, out["n_tracker"] / out["n_total"] * 100, 0.0
    )
    return out


RANK_COL = {"trackers": "n_tracker", "providers": "n_providers", "pct": "pct_tracker"}


def _footer(fig, meta):
    fig.text(
        0.5, 0.005,
        f"{meta['country']} · {meta['browser']} · {meta['n_sites']:,} health sites "
        f"matched · {meta['n_tracker_cookies']:,} tracker cookies",
        ha="center", va="bottom", fontsize=9, color=MID,
    )


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def plot_bar(top, out_dir, meta, rank_by):
    apply_theme()
    rc = RANK_COL[rank_by]
    vals = top[rc].to_numpy()
    sites = top["site"].tolist()
    y = np.arange(len(top))[::-1]  # highest at top
    colors = gradient_colors(vals)

    fig, ax = plt.subplots(figsize=(11, 0.45 * len(top) + 2))
    bars = ax.barh(y, vals, color=colors, edgecolor=BG, height=0.74)
    ax.set_yticks(y)
    ax.set_yticklabels(sites, fontsize=10)
    pad = max(vals) * 0.012
    for bar, n_t, n_p in zip(bars, top["n_tracker"], top["n_providers"]):
        primary = bar.get_width()
        ax.text(
            primary + pad, bar.get_y() + bar.get_height() / 2,
            f"{int(primary)}" + (f"  ·  {n_p} trackers" if rank_by != "providers" else f"  ·  {n_t} cookies"),
            va="center", fontsize=9, color=DARK,
        )
    label = {"trackers": "# tracker cookies", "providers": "# distinct trackers",
             "pct": "% tracker cookies"}[rank_by]
    ax.set_xlabel(label)
    ax.set_xlim(0, max(vals) * 1.22)
    ax.grid(axis="x", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title(f"Most Tracked Medical Websites — top {len(top)}", fontsize=14, pad=10)
    _footer(fig, meta)
    plt.tight_layout(rect=(0, 0.03, 1, 1))
    save_figure(out_dir, "plot_most_tracked_medical_bar.png",
                "plot_most_tracked_medical_bar.pdf")


def plot_lollipop(top, out_dir, meta, rank_by):
    apply_theme()
    rc = RANK_COL[rank_by]
    vals = top[rc].to_numpy()
    sites = top["site"].tolist()
    y = np.arange(len(top))[::-1]

    fig, ax = plt.subplots(figsize=(11, 0.45 * len(top) + 2))
    ax.hlines(y, 0, vals, color=LIGHT, lw=2.2, zorder=1)
    ax.scatter(vals, y, color=ACCENT, s=90, zorder=2, edgecolor=BG, linewidth=1)
    ax.set_yticks(y)
    ax.set_yticklabels(sites, fontsize=10)
    pad = max(vals) * 0.02
    for v, yy in zip(vals, y):
        ax.text(v + pad, yy, f"{int(v)}", va="center", fontsize=9, color=DARK)
    label = {"trackers": "# tracker cookies", "providers": "# distinct trackers",
             "pct": "% tracker cookies"}[rank_by]
    ax.set_xlabel(label)
    ax.set_xlim(0, max(vals) * 1.18)
    ax.grid(axis="x", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title(f"Most Tracked Medical Websites — top {len(top)}", fontsize=14, pad=10)
    _footer(fig, meta)
    plt.tight_layout(rect=(0, 0.03, 1, 1))
    save_figure(out_dir, "plot_most_tracked_medical_lollipop.png",
                "plot_most_tracked_medical_lollipop.pdf")


def plot_stacked(top, out_dir, meta, rank_by):
    apply_theme()
    sites = top["site"].tolist()
    n_trk = top["n_tracker"].to_numpy()
    n_other = (top["n_total"] - top["n_tracker"]).to_numpy()
    y = np.arange(len(top))[::-1]

    fig, ax = plt.subplots(figsize=(11, 0.45 * len(top) + 2))
    ax.barh(y, n_trk, color=ACCENT, edgecolor=BG, height=0.74, label="Tracker cookies")
    ax.barh(y, n_other, left=n_trk, color=LIGHT, edgecolor=BG, height=0.74,
            label="Other cookies")
    ax.set_yticks(y)
    ax.set_yticklabels(sites, fontsize=10)
    totals = top["n_total"].to_numpy()
    pad = max(totals) * 0.012
    for yy, n_t, tot, pct in zip(y, n_trk, totals, top["pct_tracker"]):
        ax.text(tot + pad, yy, f"{int(n_t)}/{int(tot)}  ({pct:.0f}%)",
                va="center", fontsize=9, color=DARK)
    ax.set_xlabel("# cookies (tracker + other)")
    ax.set_xlim(0, max(totals) * 1.25)
    ax.grid(axis="x", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(fontsize=9, loc="lower right")
    ax.set_title(f"Most Tracked Medical Websites — top {len(top)}", fontsize=14, pad=10)
    _footer(fig, meta)
    plt.tight_layout(rect=(0, 0.03, 1, 1))
    save_figure(out_dir, "plot_most_tracked_medical_stacked.png",
                "plot_most_tracked_medical_stacked.pdf")


def plot_bubble(top, out_dir, meta, rank_by):
    apply_theme()
    x = top["n_total"].to_numpy()
    yv = top["n_providers"].to_numpy()
    size = top["n_tracker"].to_numpy()
    sizes = 60 + (size / max(size.max(), 1)) * 900
    colors = gradient_colors(size)

    fig, ax = plt.subplots(figsize=(11, 7.5))
    ax.scatter(x, yv, s=sizes, c=colors, edgecolor=DARK, linewidth=0.6, alpha=0.9, zorder=2)
    for xi, yi, lbl in zip(x, yv, top["site"]):
        ax.annotate(lbl, (xi, yi), xytext=(5, 4), textcoords="offset points",
                    fontsize=8.5, color=DARK)
    ax.set_xlabel("# total cookies on site")
    ax.set_ylabel("# distinct trackers")
    ax.grid(alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title(
        f"Most Tracked Medical Websites — top {len(top)} (bubble = tracker cookies)",
        fontsize=14, pad=10,
    )
    # size legend
    for ref in sorted({int(size.min()), int(np.median(size)), int(size.max())}):
        ax.scatter([], [], s=60 + (ref / max(size.max(), 1)) * 900,
                   c=ACCENT2, edgecolor=DARK, linewidth=0.6, label=f"{ref} tracker cookies")
    ax.legend(fontsize=9, loc="upper left", labelspacing=1.4, borderpad=1.0,
              title="bubble size", title_fontsize=8)
    _footer(fig, meta)
    plt.tight_layout(rect=(0, 0.03, 1, 1))
    save_figure(out_dir, "plot_most_tracked_medical_bubble.png",
                "plot_most_tracked_medical_bubble.pdf")


VIEWS = {"bar": plot_bar, "lollipop": plot_lollipop, "stacked": plot_stacked,
         "bubble": plot_bubble}


def main(data_dir, health_csv, country, browser, out_dir, kind, top_n, rank_by):
    print("Loading health-site tracking table…")
    df = site_tracking_table(data_dir, health_csv, country, browser)
    if df.empty:
        print(f"No health sites matched for {country}/{browser}. "
              f"Check --health, --country, --browser.")
        return

    top = df.sort_values(RANK_COL[rank_by], ascending=False).head(top_n).reset_index(drop=True)
    meta = {
        "country": country, "browser": browser,
        "n_sites": int((df["n_tracker"] > 0).sum()),
        "n_tracker_cookies": int(df["n_tracker"].sum()),
    }
    print(f"  {len(df):,} health sites matched; showing top {len(top)} by {rank_by}.")
    print(top[["site", "n_tracker", "n_providers", "n_total"]].to_string(index=False))

    chosen = list(VIEWS) if kind == "all" else [kind]
    for k in chosen:
        VIEWS[k](top, out_dir, meta, rank_by)
    print(f"\nDone. Saved {len(chosen)} view(s) to {out_dir}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Rank medical/health websites by how heavily tracked they are."
    )
    parser.add_argument("--data", default=os.path.join(ROOT, "cookies_data"))
    parser.add_argument("--health", default=os.path.join(ROOT, "health_websites_1K.csv"),
                        help="Health site CSV (domain or rank,url columns).")
    parser.add_argument("--country", default="Netherlands")
    parser.add_argument("--browser", default="chromium")
    parser.add_argument("--out", default=os.path.join(ROOT, "plots", "medical"))
    parser.add_argument("--kind", default="all",
                        choices=["all", "bar", "lollipop", "stacked", "bubble"])
    parser.add_argument("--top-n", type=int, default=15)
    parser.add_argument("--rank-by", default="trackers",
                        choices=["trackers", "providers", "pct"],
                        help="Rank/measure sites by tracker cookies, distinct trackers, or %%.")
    args = parser.parse_args()
    main(args.data, args.health, args.country, args.browser, args.out,
         args.kind, args.top_n, args.rank_by)
