"""
Top tracker cookies on medical/health websites (NL crawl, Chromium).
File location: scripts/plot_scripts/plot_top_trackers_medical.py
"""

import argparse
import csv
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "plot_scripts"))

from utils import apply_theme, save_figure, dataset, ACCENT, ACCENT2, DARK, LIGHT, MID

COMPANY_NAMES = {
    "demdex.net": "Adobe Audience Manager",
    "hs-analytics.net": "HubSpot Analytics",
    "media.net": "Media.net Ads",
    "sc-static.net": "Snapchat",
    "criteo.com": "Criteo",
    "tapad.com": "Tapad / Telenor",
    "hsadspixel.net": "HubSpot Ads Pixel",
    "aim-tag.hcn.health": "HCN Health Ad Network",
    "ct.pinterest.com": "Pinterest",
    "evergage.com": "Salesforce Personalization",
    "everesttech.net": "Adobe / Everest",
    "mc.yandex.com": "Yandex Metrica",
    "bidr.io": "Beeswax DSP",
    "m.stripe.com": "Stripe",
    "doubleclick.net": "Google DoubleClick",
    "google-analytics.com": "Google Analytics",
    "facebook.com": "Meta",
    "adnxs.com": "Microsoft / Xandr",
    "rubiconproject.com": "Magnite",
    "roeye.com": "R.O. EYE",
    "trkn.us": "Claritas",
    "px.mountain.com": "MNTN",
    "pubmatic.com": "PubMatic",
    "openx.net": "OpenX",
    "casalemedia.com": "Index Exchange",
    "rlcdn.com": "LiveRamp",
    "bluekai.com": "Oracle BlueKai",
    "krxd.net": "Salesforce Krux",
    "quantserve.com": "Quantcast",
    "nr-data.net": "New Relic",
}


def load_health_domains(csv_path: str) -> set[str]:
    domains = set()
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            domains.add(row["domain"].strip().lower())
    return domains


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=os.path.join(ROOT, "cookies_data"))
    parser.add_argument(
        "--health", default=os.path.join(ROOT, "health_websites_1K.csv")
    )
    parser.add_argument("--country", default="Netherlands")
    parser.add_argument("--browser", default="chromium")
    parser.add_argument("--top_n", type=int, default=15)
    parser.add_argument("--out", default=os.path.join(ROOT, "plots", "health_trackers"))
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    health_domains = load_health_domains(args.health)
    print(f"Loaded {len(health_domains):,} health domains")

    ds = dataset(args.data)
    cookies = ds.classified_cookies

    # Filter to country/browser/health sites/tracker cookies in one pass.
    mask = (
        (cookies["country"] == args.country)
        & (cookies["browser"] == args.browser)
        & (cookies["registered_domain"].isin(health_domains))
        & (cookies["is_tracker"])
    )
    health_cookies = cookies[mask].copy()

    n_sites_total = health_cookies["domain"].nunique()
    n_cookies = len(health_cookies)
    print(f"Sites: {n_sites_total:,}, tracker cookies: {n_cookies:,}")
    if health_cookies.empty:
        print("No tracker cookies found.")
        return

    # Provider: setter_domain (registered domain of the URL that set the cookie)
    # is the most informative field; fall back to the cookie's own domain.
    health_cookies["_provider"] = health_cookies["setter_domain"].fillna(
        health_cookies["cookie_domain"].str.lstrip(".")
    )
    # Keep only third-party providers (has a dot = real domain, not bare hostname).
    health_cookies = health_cookies[
        health_cookies["_provider"].str.contains(r"\.", regex=True, na=False)
    ]

    # Lifetime for persistent cookies only (session cookies have no expiry).
    health_cookies["_lt"] = health_cookies["lifetime_days"].where(
        health_cookies["lifetime_days"] > 0
    )

    agg = (
        health_cookies.groupby("_provider", dropna=False)
        .agg(
            cookie_count=("_provider", "size"),
            site_count=("domain", "nunique"),
            median_lifetime=("_lt", "median"),
        )
        .reset_index()
    )
    agg["pct_sites"] = (agg["site_count"] / n_sites_total * 100).round(1)
    agg = agg.sort_values("pct_sites", ascending=False).head(args.top_n)

    providers = agg["_provider"].tolist()
    pct_sites = agg["pct_sites"].tolist()
    cookie_counts = agg["cookie_count"].tolist()
    med_lifetimes = agg["median_lifetime"].tolist()

    apply_theme()

    fig, axes = plt.subplots(
        1,
        2,
        figsize=(12, 5),
        gridspec_kw={"width_ratios": [1.5, 1], "wspace": 0.05},
    )
    ax, ax2 = axes
    y = np.arange(len(providers))

    # --- left panel: prevalence bars ---
    bars = ax.barh(y, pct_sites[::-1], color=ACCENT, height=0.65)
    ax.set_yticks(y)
    ax.set_yticklabels(providers[::-1], fontsize=10)

    for bar, p, n_c in zip(bars, providers[::-1], cookie_counts[::-1]):
        company = COMPANY_NAMES.get(str(p).lstrip("."), "")
        label = f"  {company}  ({n_c})" if company else f"  ({n_c})"
        ax.text(
            bar.get_width() + max(pct_sites) * 0.015,
            bar.get_y() + bar.get_height() / 2,
            label,
            va="center",
            fontsize=8.5,
            color=DARK,
        )

    ax.set_xlabel("% of health sites where tracker was observed", color=DARK)
    ax.set_xlim(0, max(pct_sites) * 1.6)
    ax.spines[["top", "right"]].set_visible(False)

    # --- right panel: median lifetime dots ---
    valid_lts = [v for v in med_lifetimes if v and not np.isnan(v)]
    max_lt = max(valid_lts) if valid_lts else 400

    ax2.scatter(med_lifetimes[::-1], y, color=ACCENT2, s=80, zorder=3)
    for i, lt in enumerate(med_lifetimes[::-1]):
        if lt and not np.isnan(lt):
            ax2.text(
                lt + max_lt * 0.04, i, f"{lt:.0f}d", va="center", fontsize=8, color=DARK
            )

    ax2.axvline(365, color=LIGHT, linestyle="--", linewidth=1.2, label="1 year")
    ax2.set_yticks(y)
    ax2.set_yticklabels([""] * len(y))
    ax2.set_xlabel(
        "Median cookie lifetime\n(persistent cookies only, days)", color=DARK
    )
    ax2.set_xlim(0, max_lt * 1.25)
    ax2.spines[["top", "right"]].set_visible(False)

    fig.suptitle(
        f"Top {args.top_n} Tracker Providers on Health Websites",
        fontsize=13,
        fontweight="bold",
        color=DARK,
        y=0.98,
    )
    fig.text(
        0.5,
        0.92,
        f"Run on {args.browser} from {args.country} on "
        f"{n_sites_total} sites with {n_cookies} tracker cookies",
        fontsize=11,
        color=DARK,
        ha="center",
        va="center",
    )

    save_figure(args.out, "top_trackers_health_sites.png")

    print("\nMedian lifetimes (days):")
    for p, lt in zip(providers, med_lifetimes):
        print(f"  {p}: {lt:.1f}d" if lt and not np.isnan(lt) else f"  {p}: n/a")


if __name__ == "__main__":
    main()
