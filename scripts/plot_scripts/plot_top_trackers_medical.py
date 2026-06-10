"""
Top tracker cookies on medical/health websites (NL crawl, Chromium).
File location: scripts/plot_scripts/plot_top_trackers_medical.py
"""

import os
import sys
import csv
import shutil
import tempfile
import argparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

_MAX_WORKERS = int(os.environ.get("COOKIE_WORKERS", "4"))
os.cpu_count = lambda: _MAX_WORKERS + 1

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from utils import apply_theme, save_figure, dataset, ACCENT, ACCENT2, DARK, LIGHT, MID

# Manually curated from public knowledge — only well-known companies included.
COMPANY_NAMES = {
    "demdex.net":           "Adobe Audience Manager",
    "hs-analytics.net":     "HubSpot Analytics",
    "media.net":            "Media.net Ads",
    "sc-static.net":        "Snapchat",
    "criteo.com":           "Criteo",
    "tapad.com":            "Tapad / Telenor",
    "hsadspixel.net":       "HubSpot Ads Pixel",
    "aim-tag.hcn.health":   "HCN Health Ad Network",
    "ct.pinterest.com":     "Pinterest",
    "evergage.com":         "Salesforce Personalization",
    "everesttech.net":      "Adobe / Everest",
    "mc.yandex.com":        "Yandex Metrica",
    "bidr.io":              "Beeswax DSP",
    "m.stripe.com":         "Stripe",
    "doubleclick.net":      "Google DoubleClick",
    "google-analytics.com": "Google Analytics",
    "facebook.com":         "Meta",
    "adnxs.com":            "Microsoft / Xandr",
    "rubiconproject.com":   "Magnite",
    "roeye.com":            "R.O. EYE",
    "trkn.us":              "Claritas",
    "px.mountain.com":      "MNTN",
    "pubmatic.com":         "PubMatic",
    "openx.net":            "OpenX",
    "casalemedia.com":      "Index Exchange",
    "rlcdn.com":            "LiveRamp",
    "bluekai.com":          "Oracle BlueKai",
    "krxd.net":             "Salesforce Krux",
    "quantserve.com":       "Quantcast",
    "vimeo.com":            "Bending Spoons",
    "dpm.demdex.net":       "Adobe",
    "nr-data.net":          "New Relic",
}


def load_health_domains(csv_path):
    domains = set()
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            domains.add(row["domain"].strip().lower())
    return domains


def domain_to_filename(domain):
    return domain.replace(".", "_") + ".json"


def build_index(data_dir):
    index = {}
    for subdir in os.listdir(data_dir):
        subpath = os.path.join(data_dir, subdir)
        if not os.path.isdir(subpath):
            continue
        for fname in os.listdir(subpath):
            if fname.endswith(".json"):
                index[fname] = os.path.join(subpath, fname)
    return index


def build_health_data_dir(data_dir, health_domains):
    print("Building filename index...")
    index = build_index(data_dir)
    print(f"Index built: {len(index):,} JSON files")
    tmp = tempfile.mkdtemp(prefix="cookies_health_")
    found = missing = 0
    missing_domains = []
    for domain in health_domains:
        fname = domain_to_filename(domain)
        src = index.get(fname)
        if src is None:
            missing += 1
            missing_domains.append(domain)
            continue
        subdir = os.path.basename(os.path.dirname(src))
        dst_dir = os.path.join(tmp, subdir)
        os.makedirs(dst_dir, exist_ok=True)
        try:
            os.symlink(src, os.path.join(dst_dir, fname))
        except (OSError, NotImplementedError):
            shutil.copy2(src, os.path.join(dst_dir, fname))
        found += 1
    print(f"[health filter] {found} JSONs linked, {missing} not in crawl")
    if missing_domains:
        for d in sorted(missing_domains):
            print(f"  missing: {d}")
    return tmp, found


def looks_like_first_party(provider: str) -> bool:
    return "." not in provider.lstrip(".")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top_n", type=int, default=15)
    parser.add_argument("--workers", type=int, default=_MAX_WORKERS)
    args = parser.parse_args()
    os.cpu_count = lambda: args.workers + 1

    data_dir = os.path.join(ROOT, "cookies_data", "Netherlands", "chromium")
    csv_path = os.path.join(ROOT, "health_websites_1K.csv")
    out_dir  = os.path.join(ROOT, "plots", "health_trackers")
    os.makedirs(out_dir, exist_ok=True)

    health_domains = load_health_domains(csv_path)
    print(f"Loaded {len(health_domains)} health domains")

    tmp_dir, n_found = build_health_data_dir(data_dir, health_domains)
    if n_found == 0:
        print("No health domain files found.")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return

    try:
        ds = dataset(tmp_dir)
        cookies = ds.cookies.copy()

        domain_col = "bare_domain" if "bare_domain" in cookies.columns else "domain"
        cookies[domain_col] = cookies[domain_col].str.lstrip(".").str.lower()

        health_cookies = (
            cookies[cookies["is_tracker"].astype(bool)].copy()
            if "is_tracker" in cookies.columns else cookies.copy()
        )

        n_sites_total = health_cookies[domain_col].nunique()
        n_cookies     = len(health_cookies)
        print(f"Sites: {n_sites_total}, tracker cookies: {n_cookies}")
        if health_cookies.empty:
            print("No tracker cookies found.")
            return

        provider_col      = next(
            (c for c in ("tracker_provider", "provider", "cookie_provider") if c in health_cookies.columns),
            None,
        )
        cookie_domain_col = "domain" if "domain" in health_cookies.columns else domain_col
        if provider_col:
            health_cookies["_provider"] = (
                health_cookies[provider_col]
                .fillna(health_cookies[cookie_domain_col].str.lstrip("."))
            )
        else:
            health_cookies["_provider"] = health_cookies[cookie_domain_col].str.lstrip(".")

        health_cookies = health_cookies[
            ~health_cookies["_provider"].apply(looks_like_first_party)
        ]

        lt_col = "lifetime_days" if "lifetime_days" in health_cookies.columns else None
        if lt_col:
            health_cookies["_lt"] = health_cookies[lt_col].where(health_cookies[lt_col] > 0)

        agg_dict = dict(
            cookie_count=("_provider", "size"),
            site_count=(domain_col, "nunique"),
        )
        if lt_col:
            agg_dict["median_lifetime"] = ("_lt", "median")

        agg = (
            health_cookies.groupby("_provider", dropna=False)
            .agg(**agg_dict)
            .reset_index()
        )
        agg["pct_sites"] = (agg["site_count"] / n_sites_total * 100).round(1)
        agg = agg.sort_values("pct_sites", ascending=False).head(args.top_n)

        providers     = agg["_provider"].tolist()
        pct_sites     = agg["pct_sites"].tolist()
        cookie_counts = agg["cookie_count"].tolist()
        has_lifetime  = lt_col and "median_lifetime" in agg.columns
        med_lifetimes = agg["median_lifetime"].tolist() if has_lifetime else []

        apply_theme()

        fig, axes = plt.subplots(
            1, 2, figsize=(12, 5),
            gridspec_kw={"width_ratios": [1.5, 1], "wspace": 0.05},
        )
        ax, ax2 = axes
        y = np.arange(len(providers))

        # --- left panel: prevalence bars ---
        bars = ax.barh(y, pct_sites[::-1], color=ACCENT, height=0.65)
        ax.set_yticks(y)
        ax.set_yticklabels(providers[::-1], fontsize=10)

        # company name + cookie count to the right of bar
        for bar, p, n_c in zip(bars, providers[::-1], cookie_counts[::-1]):
            company = COMPANY_NAMES.get(str(p).lstrip("."), "")
            label = f"  {company}  ({n_c})" if company else f"  ({n_c})"
            ax.text(
                bar.get_width() + max(pct_sites) * 0.015,
                bar.get_y() + bar.get_height() / 2,
                label,
                va="center", fontsize=8.5, color=DARK,
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
                ax2.text(lt + max_lt * 0.04, i, f"{lt:.0f}d",
                         va="center", fontsize=8, color=DARK)

        ax2.axvline(365, color=LIGHT, linestyle="--", linewidth=1.2, label="1 year")
        ax2.set_yticks(y)
        ax2.set_yticklabels([""] * len(y))
        ax2.set_xlabel("Median cookie lifetime\n(persistent cookies only, days)", color=DARK)
        ax2.set_xlim(0, max_lt * 1.25)
        ax2.spines[["top", "right"]].set_visible(False)

        fig.suptitle(
            f"Top {args.top_n} Tracker Providers on Health Websites",
            fontsize=13,
            fontweight="bold",
            color=DARK,
            y=0.98
        )

        fig.text(
            0.5, 0.92,
            f"Run on Chromium from the Netherlands on {n_sites_total} sites with {n_cookies} tracker cookies",
            fontsize=11,
            fontweight="normal",
            color=DARK,
            ha="center",
            va="center"
        )

        save_figure(out_dir, "top_trackers_health_sites.png")

        if has_lifetime:
            print("\nMedian lifetimes (days):")
            for p, lt in zip(providers, med_lifetimes):
                print(f"  {p}: {lt:.1f}d" if lt and not np.isnan(lt) else f"  {p}: n/a")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()