"""
Top Third-Party Domains Across Websites

This script analyzes processed cookie data and identifies
the most common third-party tracker domains across websites.

It counts UNIQUE websites per tracker domain,
not total cookies.

Usage:
    python scripts/plot_scripts/plot_party_distribution.py ^
        --data cookies_data_processed ^
        --out plots
"""

import argparse
import json
import os
from collections import defaultdict

import matplotlib.pyplot as plt
import pandas as pd
import tldextract


# ==========================================
# THEME
# ==========================================

BG = "#f7f3ee"
DARK = "#2c2c2c"
ACCENT = "#c97b63"


def apply_theme():

    plt.style.use("default")

    plt.rcParams.update({
        "figure.facecolor": BG,
        "axes.facecolor": BG,
        "savefig.facecolor": BG,
        "axes.edgecolor": BG,
        "text.color": DARK,
        "axes.labelcolor": DARK,
        "xtick.color": DARK,
        "ytick.color": DARK,
        "font.size": 12
    })


# ==========================================
# DOMAIN NORMALIZATION
# ==========================================

def get_base_domain(hostname: str):
    """
    Extract registrable/base domain.

    Examples:
        ads.google.com -> google.com
        analytics.facebook.net -> facebook.net
    """

    if not hostname:
        return None

    extracted = tldextract.extract(hostname.lstrip("."))

    if not extracted.domain or not extracted.suffix:
        return None

    return f"{extracted.domain}.{extracted.suffix}"


# ==========================================
# DATA LOADING
# ==========================================

def load_tracker_data(data_dir):

    # tracker_domain -> set(websites)
    tracker_sites = defaultdict(set)

    # =====================================
    # DEBUG STATS
    # =====================================

    total_sites = 0
    sites_with_third_party = set()

    for filename in os.listdir(data_dir):

        if not filename.endswith(".json"):
            continue

        total_sites += 1

        path = os.path.join(data_dir, filename)

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

        except Exception as e:
            print(f"Failed loading {filename}: {e}")
            continue

        target_url = data.get("target_url", "")

        if not target_url:
            print(f"Skipping {filename}: no target_url")
            continue

        website = (
            target_url
            .replace("https://", "")
            .replace("http://", "")
            .strip("/")
        )

        cookies = data.get("cookies", [])

        # =====================================
        # TRACK WHETHER SITE HAS 3RD-PARTY
        # =====================================

        found_third_party = False

        for cookie in cookies:

            party_type = cookie.get("party_type")

            if party_type != "third_party":
                continue

            found_third_party = True

            domain = cookie.get("domain")

            if not domain:
                continue

            tracker_domain = get_base_domain(domain)

            if not tracker_domain:
                continue

            tracker_sites[tracker_domain].add(website)

        # =====================================
        # SAVE SITE
        # =====================================

        if found_third_party:
            sites_with_third_party.add(website)

    # =====================================
    # PRINT DEBUG INFO
    # =====================================

    print(f"Total JSON files: {total_sites}")
    print(f"Sites with third-party cookies: {len(sites_with_third_party)}")

    # =====================================
    # BUILD DATAFRAME
    # =====================================

    rows = []

    for tracker_domain, websites in tracker_sites.items():

        rows.append({
            "tracker_domain": tracker_domain,
            "website_count": len(websites)
        })

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    df = df.sort_values(
        by="website_count",
        ascending=False
    )

    return df


# ==========================================
# PLOTTING
# ==========================================

def plot_top_trackers(data_dir, out_dir, top_n=15):

    apply_theme()

    df = load_tracker_data(data_dir)

    if df.empty:
        print("No tracker data found.")
        return

    top_df = df.head(top_n)

    fig, ax = plt.subplots(figsize=(11, 7))

    # Reverse for nicer top-down ordering
    domains = top_df["tracker_domain"][::-1]
    counts = top_df["website_count"][::-1]

    bars = ax.barh(
        domains,
        counts
    )

    ax.set_title(
        f"Top {top_n} Third-Party Domains",
        fontsize=16,
        fontweight="bold",
        pad=20
    )

    ax.set_xlabel("Number of Websites")

    # Remove clutter
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Value labels
    for bar in bars:

        width = bar.get_width()

        ax.text(
            width + 0.2,
            bar.get_y() + bar.get_height() / 2,
            f"{int(width)}",
            va="center"
        )

    plt.tight_layout()

    os.makedirs(out_dir, exist_ok=True)

    out_path = os.path.join(
        out_dir,
        "plot_top_tracker_domains.png"
    )

    plt.savefig(
        out_path,
        dpi=300,
        bbox_inches="tight"
    )

    print(f"Saved → {out_path}")

    plt.close()


# ==========================================
# MAIN
# ==========================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--data",
        default="./cookies_data_processed",
        help="Directory containing processed cookie JSON files."
    )

    parser.add_argument(
        "--out",
        default="./plots",
        help="Directory to save plots."
    )

    parser.add_argument(
        "--top",
        type=int,
        default=15,
        help="Number of top trackers to display."
    )

    args = parser.parse_args()

    plot_top_trackers(
        data_dir=args.data,
        out_dir=args.out,
        top_n=args.top
    )