"""
Cross-country tracker cookie comparison (Chromium crawl).
File location: scripts/plot_scripts/plot_trackers_by_country.py

Compares tracker cookie behaviour across VPN exit locations:
  NL, RO, SG, JP, US, CA

Each of the four panels is saved as its own PNG and PDF file.

Usage:
  python plot_trackers_by_country.py
  python plot_trackers_by_country.py --countries NL US CA --top_providers 10
"""

import argparse
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "plot_scripts"))

from utils import (
    apply_theme,
    dataset,
    ACCENT,
    ACCENT2,
    DARK,
    LIGHT,
    MID,
    BG,
)

BROWSER = "chromium"

# Country display labels (dataset code → full name, for plot labels)
COUNTRY_LABELS = {
    "Netherlands": "Netherlands",
    "CA": "Canada",
    "SG": "Singapore",
    "US": "United States",
    "JP": "Japan",
}


# ── helpers ───────────────────────────────────────────────────────────────────


def save_panel(fig, out_dir: str, stem: str) -> None:
    for ext in ("png", "pdf"):
        path = os.path.join(out_dir, f"{stem}.{ext}")
        fig.savefig(path, bbox_inches="tight", dpi=150 if ext == "png" else None)
        print(f"Saved {path}")
    plt.close(fig)


def provider_col(t):
    """Resolve best tracker provider label per row."""
    t = t.copy()
    t["_provider"] = t["setter_domain"].fillna(t["cookie_domain"].str.lstrip("."))
    return t[t["_provider"].str.contains(r"\.", regex=True, na=False)]


# ── panels ────────────────────────────────────────────────────────────────────


def plot_tracker_reach(per_country: dict, out_dir: str) -> None:
    """A: % of sites with at least one tracker cookie, per country."""
    countries = list(per_country.keys())
    labels = [COUNTRY_LABELS.get(c, c) for c in countries]
    values = [per_country[c]["pct_with_tracker"] for c in countries]

    # Sort descending
    order = np.argsort(values)[::-1]
    labels = [labels[i] for i in order]
    values = [values[i] for i in order]

    fig, ax = plt.subplots(figsize=(7, 4.5))
    x = np.arange(len(labels))
    bars = ax.bar(x, values, color=ACCENT, width=0.55)
    ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=9, color=DARK)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("% of Sites", fontsize=10)
    ax.set_ylim(0, min(100, max(values) * 1.18))
    ax.set_title(
        "Sites Exposed to at Least One Tracker Cookie",
        fontweight="bold", color=DARK,
    )
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter())

    save_panel(fig, out_dir, "country_A_tracker_reach")


def plot_tracker_load(per_country: dict, out_dir: str) -> None:
    """B: Distribution of tracker cookie count per site (violin + median marker)."""
    countries = list(per_country.keys())
    labels = [COUNTRY_LABELS.get(c, c) for c in countries]
    data = [per_country[c]["trackers_per_site"] for c in countries]

    # Sort by median descending
    medians = [np.median(d) for d in data]
    order = np.argsort(medians)[::-1]
    labels = [labels[i] for i in order]
    data = [data[i] for i in order]

    fig, ax = plt.subplots(figsize=(7, 4.5))
    parts = ax.violinplot(data, positions=np.arange(len(labels)), showmedians=False,
                          showextrema=False)
    for pc in parts["bodies"]:
        pc.set_facecolor(ACCENT)
        pc.set_alpha(0.75)
        pc.set_edgecolor(DARK)
        pc.set_linewidth(0.8)

    # Overlay median dots
    for i, d in enumerate(data):
        med = np.median(d)
        ax.scatter(i, med, color=DARK, s=40, zorder=3)
        ax.text(i, med + 0.25, f"{med:.1f}", ha="center", va="bottom",
                fontsize=8.5, color=DARK)

    ax.set_xticks(np.arange(len(labels)))
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("Tracker Cookies per Site", fontsize=10)
    ax.set_title(
        "Tracker Cookie Load per Site",
        fontweight="bold", color=DARK,
    )
    ax.spines[["top", "right"]].set_visible(False)

    save_panel(fig, out_dir, "country_B_tracker_load")


def plot_lifetime_by_country(per_country: dict, out_dir: str) -> None:
    """C: Median persistent tracker cookie lifetime per country (bar + IQR error bars)."""
    countries = list(per_country.keys())
    labels = [COUNTRY_LABELS.get(c, c) for c in countries]
    medians, q25s, q75s = [], [], []

    for c in countries:
        days = per_country[c]["persistent_lifetime_days"]
        if len(days) == 0:
            medians.append(0); q25s.append(0); q75s.append(0)
            continue
        medians.append(np.median(days))
        q25s.append(np.percentile(days, 25))
        q75s.append(np.percentile(days, 75))

    # Sort by median descending
    order = np.argsort(medians)[::-1]
    labels   = [labels[i]  for i in order]
    medians  = [medians[i] for i in order]
    err_low  = [medians[i] - q25s[order[i]] for i in range(len(order))]
    err_high = [q75s[order[i]] - medians[i] for i in range(len(order))]

    fig, ax = plt.subplots(figsize=(7, 4.5))
    x = np.arange(len(labels))
    ax.bar(x, medians, color=ACCENT2, width=0.55, zorder=2)
    ax.errorbar(x, medians, yerr=[err_low, err_high], fmt="none",
                color=DARK, capsize=5, linewidth=1.4, zorder=3)

    # 1-year reference line
    ax.axhline(365, color=LIGHT, linestyle="--", linewidth=1.2, label="1 year")
    ax.legend(fontsize=9)

    for xi, med in zip(x, medians):
        ax.text(xi, med + max(err_high) * 0.05, f"{med:.0f}d",
                ha="center", va="bottom", fontsize=8.5, color=DARK)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("Lifetime (days)", fontsize=10)
    ax.set_title(
        "Persistent Tracker Cookie Lifetime by Country",
        fontweight="bold", color=DARK,
    )
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_ylim(0, max(medians) * 1.3)

    save_panel(fig, out_dir, "country_C_lifetime_by_country")


def plot_provider_heatmap(per_country: dict, top_n: int, out_dir: str) -> None:
    """D: Heatmap — top tracker providers (rows) × countries (cols), cell = % of sites."""
    countries = list(per_country.keys())
    col_labels = [COUNTRY_LABELS.get(c, c) for c in countries]

    # Collect global top providers by average prevalence across countries
    from collections import defaultdict
    provider_scores: dict[str, float] = defaultdict(float)
    for c in countries:
        for prov, pct in per_country[c]["provider_prevalence"].items():
            provider_scores[prov] += pct
    top_providers = sorted(provider_scores, key=provider_scores.get, reverse=True)[:top_n]

    # Build matrix: rows = providers, cols = countries
    matrix = np.zeros((len(top_providers), len(countries)))
    for j, c in enumerate(countries):
        prev = per_country[c]["provider_prevalence"]
        for i, prov in enumerate(top_providers):
            matrix[i, j] = prev.get(prov, 0.0)

    fig, ax = plt.subplots(figsize=(8, 0.55 * top_n + 2))
    im = ax.imshow(matrix, aspect="auto", cmap="YlOrBr")

    ax.set_xticks(np.arange(len(col_labels)))
    ax.set_xticklabels(col_labels, fontsize=11)
    ax.set_yticks(np.arange(len(top_providers)))
    ax.set_yticklabels(top_providers, fontsize=8.5)
    ax.xaxis.set_ticks_position("bottom")

    # Annotate cells
    thresh = matrix.max() / 2
    for i in range(len(top_providers)):
        for j in range(len(countries)):
            val = matrix[i, j]
            color = "white" if val > thresh else DARK
            ax.text(j, i, f"{val:.1f}%", ha="center", va="center",
                    fontsize=7.5, color=color)

    cbar = fig.colorbar(im, ax=ax, shrink=0.6, pad=0.02)
    cbar.set_label("% of sites in country", fontsize=9)
    cbar.ax.tick_params(labelsize=8)

    ax.set_title(
        "Tracker Provider Reach Across Countries",
        fontweight="bold", color=DARK, pad=10,
    )
    fig.tight_layout()

    save_panel(fig, out_dir, "country_D_provider_heatmap")


# ── data prep ─────────────────────────────────────────────────────────────────


def build_per_country(cookies, countries: list[str]) -> dict:
    """Precompute all per-country metrics in one pass."""
    base = cookies[cookies["browser"] == BROWSER]
    result = {}

    for country in countries:
        df = base[base["country"] == country]
        if df.empty:
            print(f"  WARNING: no data for {country}, skipping")
            continue

        total_sites = df["domain"].nunique()
        t = df[df["is_tracker"]].copy()

        # A: % sites with ≥1 tracker
        sites_with_tracker = t["domain"].nunique()
        pct_with_tracker = sites_with_tracker / total_sites * 100

        # B: tracker cookie count per site (include sites with 0)
        per_site = t.groupby("domain").size()
        all_sites = df["domain"].unique()
        trackers_per_site = per_site.reindex(all_sites, fill_value=0).values

        # C: persistent lifetime (> 1 day)
        persistent = t[t["lifetime_days"] > 1]["lifetime_days"].clip(upper=730).values

        # D: provider prevalence (% of sites in country seeing each provider)
        t_p = provider_col(t)
        provider_prevalence = (
            t_p.groupby("_provider")["domain"].nunique() / total_sites * 100
        ).to_dict()

        result[country] = {
            "total_sites": total_sites,
            "pct_with_tracker": pct_with_tracker,
            "trackers_per_site": trackers_per_site,
            "persistent_lifetime_days": persistent,
            "provider_prevalence": provider_prevalence,
        }
        print(
            f"  {COUNTRY_LABELS.get(country, country)}: {total_sites:,} sites, "
            f"{pct_with_tracker:.1f}% tracked"
        )

    return result


# ── main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=os.path.join(ROOT, "cookies_data"))
    parser.add_argument(
        "--countries",
        nargs="+",
        default=["Netherlands", "Romania", "Singapore", "Japan",
                 "United States", "Canada"],
    )
    parser.add_argument("--top_providers", type=int, default=12)
    parser.add_argument("--out", default=os.path.join(ROOT, "plots", "by_country"))
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    print("Loading dataset...")
    ds = dataset(args.data)
    cookies = ds.classified_cookies

    print(f"Building per-country metrics for: {', '.join(args.countries)}")
    per_country = build_per_country(cookies, args.countries)

    if not per_country:
        print("No data found for any country. Check --data path and country names.")
        return

    apply_theme()

    print("\nGenerating plots...")
    plot_tracker_reach(per_country, args.out)
    plot_tracker_load(per_country, args.out)
    plot_lifetime_by_country(per_country, args.out)
    plot_provider_heatmap(per_country, args.top_providers, args.out)

    print(f"\nAll 8 files (4 × PNG + PDF) saved to: {args.out}")


if __name__ == "__main__":
    main()