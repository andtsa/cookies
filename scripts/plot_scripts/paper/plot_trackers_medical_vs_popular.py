"""
Health vs. non-health website tracker comparison (NL crawl, Chromium).
File location: scripts/plot_scripts/plot_trackers_medical_vs_popular.py

Each of the four panels is saved as its own PNG and PDF file.

Usage:
  python plot_trackers_medical_vs_popular.py               # full dataset
  python plot_trackers_medical_vs_popular.py --sample 2000 # random 2000 non-health sites
"""

import argparse
import csv
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "plot_scripts"))

from utils import (
    apply_theme,
    save_figure,
    dataset,
    ACCENT,
    ACCENT2,
    DARK,
    LIGHT,
    MID,
    BG,
)


def load_health_domains(csv_path: str) -> set[str]:
    domains = set()
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            domains.add(row["domain"].strip().lower())
    return domains


def tracker_cookies(cookies):
    return cookies[cookies["is_tracker"]].copy()


def with_provider(t):
    """Add ``_provider`` column: setter_domain where available, else cookie_domain."""
    t = t.copy()
    t["_provider"] = t["setter_domain"].fillna(t["cookie_domain"].str.lstrip("."))
    return t[t["_provider"].str.contains(r"\.", regex=True, na=False)]


def save_panel(fig, out_dir: str, stem: str) -> None:
    """Save a figure as both PNG and PDF."""
    for ext in ("png", "pdf"):
        path = os.path.join(out_dir, f"{stem}.{ext}")
        fig.savefig(path, bbox_inches="tight", dpi=150 if ext == "png" else None)
        print(f"Saved {path}")


# ── panels ────────────────────────────────────────────────────────────────────


def plot_session_split(h_t, n_t, subtitle: str, out_dir: str) -> None:
    """A: Stacked bar — session / short-lived / persistent tracker cookies."""

    def split(t):
        total = len(t)
        session = t["lifetime_days"].isna().sum()
        short = ((t["lifetime_days"] > 0) & (t["lifetime_days"] <= 1)).sum()
        persistent = (t["lifetime_days"] > 1).sum()
        return session / total * 100, short / total * 100, persistent / total * 100

    h_sess, h_short, h_pers = split(h_t)
    n_sess, n_short, n_pers = split(n_t)

    x, w = np.arange(2), 0.45
    se_v = [n_sess, h_sess]
    sh_v = [n_short, h_short]
    p_v = [n_pers, h_pers]

    fig, ax = plt.subplots(figsize=(6, 5))
    ax.bar(x, se_v, w, color=LIGHT, label="Session (no expiry date)")
    ax.bar(x, sh_v, w, bottom=se_v, color=MID, label="Short-lived persistent (≤ 1 day)")
    ax.bar(
        x,
        p_v,
        w,
        bottom=[s + sh for s, sh in zip(se_v, sh_v)],
        color=ACCENT,
        label="Persistent (> 1 day)",
    )

    for i, (sev, shv, pv) in enumerate(zip(se_v, sh_v, p_v)):
        bottom = 0
        for val, col in [(sev, DARK), (shv, DARK), (pv, "white")]:
            if val > 2:
                ax.text(
                    i,
                    bottom + val / 2,
                    f"{val:.1f}%",
                    ha="center",
                    va="center",
                    fontsize=9,
                    fontweight="bold",
                    color=col,
                )
            bottom += val

    ax.set_xticks(x)
    ax.set_xticklabels(["Non-health", "Health"])
    ax.set_ylabel("% of Tracker Cookies")
    ax.set_ylim(0, 110)
    ax.legend(fontsize=8.5, loc="upper right")
    ax.set_title("Tracker Cookie Lifetime Categories", fontweight="bold", color=DARK)
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.5, 0.01, subtitle, ha="center", fontsize=9, color=MID)

    save_panel(fig, out_dir, "panel_A_cookie_lifetime_categories")
    plt.close(fig)


def plot_tracker_count(h_cook, n_cook, h_total, n_total, subtitle: str, out_dir: str,
                       thresholds=(1, 3, 5, 10)) -> None:
    """B: % of sites with at least N tracker cookies."""

    def frac_above(cookies, total, thresh):
        per_site = cookies[cookies["is_tracker"]].groupby("domain").size()
        return (per_site >= thresh).sum() / total * 100

    x, w = np.arange(len(thresholds)), 0.35
    h_v = [frac_above(h_cook, h_total, t) for t in thresholds]
    n_v = [frac_above(n_cook, n_total, t) for t in thresholds]

    fig, ax = plt.subplots(figsize=(6, 5))
    ax.bar(x - w / 2, n_v, w, color=ACCENT2, label="Non-health")
    ax.bar(x + w / 2, h_v, w, color=ACCENT, label="Health")
    ax.set_xticks(x)
    ax.set_xticklabels([f"≥{t} trackers" for t in thresholds])
    ax.set_ylabel("% of Sites")
    ax.legend(fontsize=9)
    ax.set_title("Tracker Cookies per Site", fontweight="bold", color=DARK)
    ax.spines[["top", "right"]].set_visible(False)
    for xi, (nv, hv) in enumerate(zip(n_v, h_v)):
        ax.text(xi - w / 2, nv + 0.4, f"{nv:.1f}%", ha="center", fontsize=7.5, color=DARK)
        ax.text(xi + w / 2, hv + 0.4, f"{hv:.1f}%", ha="center", fontsize=7.5, color=DARK)
    fig.text(0.5, 0.01, subtitle, ha="center", fontsize=9, color=MID)

    save_panel(fig, out_dir, "panel_B_tracker_cookies_per_site")
    plt.close(fig)


def plot_providers_diff(h_t, n_t, h_total, n_total, top_n: int, subtitle: str,
                        out_dir: str) -> None:
    """C: Diverging bar — providers where health and non-health differ most."""
    h_prev = h_t.groupby("_provider")["domain"].nunique() / h_total * 100
    n_prev = n_t.groupby("_provider")["domain"].nunique() / n_total * 100

    all_p = set(h_prev.index) | set(n_prev.index)
    diff = {p: h_prev.get(p, 0) - n_prev.get(p, 0) for p in all_p}
    top = sorted(diff.items(), key=lambda x: abs(x[1]), reverse=True)[:top_n]
    top = sorted(top, key=lambda x: x[1])

    providers = [d[0] for d in top]
    values = [d[1] for d in top]
    colors = [ACCENT if v > 0 else ACCENT2 for v in values]

    fig, ax = plt.subplots(figsize=(8, 6))
    y = np.arange(len(providers))
    ax.barh(y, values, color=colors, height=0.65)
    ax.set_yticks(y)
    ax.set_yticklabels(providers, fontsize=8.5)
    ax.axvline(0, color=DARK, linewidth=0.8)
    ax.set_xlabel("Difference in tracker prevalence (% sites, health minus non-health)", labelpad=8)
    ax.legend(
        handles=[
            mpatches.Patch(color=ACCENT, label="More common on health sites"),
            mpatches.Patch(color=ACCENT2, label="More common on non-health sites"),
        ],
        fontsize=8,
        loc="lower right",
    )
    ax.set_title("Tracker Providers in Health vs Non-Health Sites", fontweight="bold", color=DARK)
    ax.spines[["top", "right"]].set_visible(False)
    fig.subplots_adjust(bottom=0.12)

    save_panel(fig, out_dir, "panel_C_tracker_providers_diff")
    plt.close(fig)


def plot_lifetime_split(h_t, n_t, subtitle: str, out_dir: str) -> None:
    """D: Two stacked histograms of persistent cookie lifetime (health on top, non-health below)."""
    bins = np.linspace(0, 400, 41)

    fig, (ax_h, ax_n) = plt.subplots(2, 1, figsize=(7, 7), sharex=True)
    fig.subplots_adjust(hspace=0.1)

    for ax, t, label, color in [
        (ax_h, h_t, "Health Sites", ACCENT),
        (ax_n, n_t, "Non-health Sites", ACCENT2),
    ]:
        data = t.loc[t["lifetime_days"] > 1, "lifetime_days"].clip(upper=400)
        ax.hist(data, bins=bins, color=color, alpha=0.85)
        med = data.median()
        ax.axvline(
            med,
            color=DARK,
            linestyle="--",
            linewidth=1.4,
            label=f"Median: {med:.0f} days",
        )
        ax.axvline(365, color=LIGHT, linestyle=":", linewidth=1.2, label="1 year")
        ax.set_ylabel("Cookie Count")
        ax.legend(fontsize=8)
        ax.spines[["top", "right"]].set_visible(False)

    ax_n.set_xlabel("Persistent Cookie Lifetime (days, capped at 400)")
    ax_h.set_xticklabels([])
    ax_h.set_title("Persistent Tracker Cookie Lifetime", fontweight="bold", color=DARK)
    ax_h.text(
        0.5, 0.97, "(Health Sites)",
        transform=ax_h.transAxes, ha="center", va="top",
        fontsize=10, color=DARK, fontweight="bold",
        bbox=dict(facecolor=BG, edgecolor="none", pad=2),
    )
    ax_n.text(
        0.5, 0.97, "(Non-health Sites)",
        transform=ax_n.transAxes, ha="center", va="top",
        fontsize=10, color=DARK, fontweight="bold",
    )
    fig.text(0.5, 0.01, subtitle, ha="center", fontsize=9, color=MID)

    save_panel(fig, out_dir, "panel_D_persistent_lifetime")
    plt.close(fig)


# ── main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=os.path.join(ROOT, "cookies_data"))
    parser.add_argument(
        "--health", default=os.path.join(ROOT, "health_websites_1K.csv")
    )
    parser.add_argument("--country", default="Netherlands")
    parser.add_argument("--browser", default="chromium")
    parser.add_argument("--top_n", type=int, default=12)
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        metavar="N",
        help="Randomly sample N non-health sites (omit for full dataset).",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default=os.path.join(ROOT, "plots", "health_vs_all"))
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    health_domains = load_health_domains(args.health)
    print(f"Loaded {len(health_domains):,} health domains")

    ds = dataset(args.data)
    cookies = ds.cookies

    base = cookies[
        (cookies["country"] == args.country) & (cookies["browser"] == args.browser)
    ]
    is_health = base["registered_domain"].isin(health_domains)
    h_cook = base[is_health].copy()
    n_cook = base[~is_health].copy()

    if args.sample is not None:
        n_sites = n_cook["domain"].unique()
        rng = np.random.default_rng(args.seed)
        sampled = rng.choice(
            n_sites, size=min(args.sample, len(n_sites)), replace=False
        )
        n_cook = n_cook[n_cook["domain"].isin(sampled)]
        print(f"[sample mode] {len(sampled):,} non-health sites (seed={args.seed})")

    h_total = h_cook["domain"].nunique()
    n_total = n_cook["domain"].nunique()
    print(f"Health: {h_total:,} sites, {len(h_cook):,} cookies")
    print(f"Non-health: {n_total:,} sites, {len(n_cook):,} cookies")

    h_t = with_provider(tracker_cookies(h_cook))
    n_t = with_provider(tracker_cookies(n_cook))
    print(f"Health tracker cookies: {len(h_t):,}, non-health: {len(n_t):,}")

    sample_note = (
        f", random sample of {n_total:,} non-health sites" if args.sample else ""
    )
    subtitle = (
        f"{h_total:,} health sites vs {n_total:,} non-health sites — "
        f"{args.browser} from {args.country}{sample_note}"
    )

    apply_theme()

    plot_session_split(h_t, n_t, subtitle, args.out)
    plot_tracker_count(h_cook, n_cook, h_total, n_total, subtitle, args.out)
    plot_providers_diff(h_t, n_t, h_total, n_total, args.top_n, subtitle, args.out)
    plot_lifetime_split(h_t, n_t, subtitle, args.out)

    print(f"\nAll 8 files (4 × PNG + PDF) saved to: {args.out}")


if __name__ == "__main__":
    main()
