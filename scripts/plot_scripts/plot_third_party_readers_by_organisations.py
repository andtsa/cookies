import json
from collections import defaultdict

import pandas as pd
import matplotlib.pyplot as plt

from utils import (
    apply_theme,
    save_figure,
    ACCENT,
COLORS
)

INPUT_FILE = "../../reads_filtered.json"
OUT_DIR = "plots"


# ------------------------------------------------------------------
# Domain -> Organization mapping
# ------------------------------------------------------------------

ORG_MAP = {
    # Google
    "googletagmanager.com": "Google",
    "googleadservices.com": "Google",
    "doubleclick.net": "Google",
    "googleapis.com": "Google",
    "gstatic.com": "Google",
    "googlesyndication.com": "Google",
    "google-analytics.com": "Google",
    "googletagservices.com": "Google",
    "google.com": "Google",

    # Microsoft
    "clarity.ms": "Microsoft",
    "bing.com": "Microsoft",
    "microsoft.com": "Microsoft",

    # Meta
    "facebook.net": "Meta",
    "facebook.com": "Meta",
    "fbcdn.net": "Meta",

    # Adobe
    "adobedtm.com": "Adobe",

    # LinkedIn
    "licdn.com": "LinkedIn",

    # Amazon
    "awswaf.com": "Amazon",
    "amazon-adsystem.com": "Amazon",
    "amazonaws.com": "Amazon",

    # Reddit
    "redditstatic.com": "Reddit",

    # Twitter / X
    "ads-twitter.com": "X",

    # Yandex
    "yandex.ru": "Yandex",
    "yastatic.net": "Yandex",
    "yandex.com": "Yandex",
    "yandex.net": "Yandex",
    "ya.ru": "Yandex",
    "mc.yandex.ru": "Yandex",
    "passport.yandex.ru": "Yandex",
    "an.yandex.ru": "Yandex",
    "ads6.adfox.ru": "Yandex",

    # VK / Mail.ru
    "mail.ru": "VK",

    # TrustArc
    "trustarc.com": "TrustArc",

    # OneTrust
    "cookielaw.org": "OneTrust",

    # Oracle
    "bluekai.com": "Oracle",
    "addthis.com": "Oracle",
}


# ------------------------------------------------------------------
# Load data
# ------------------------------------------------------------------

def load_organization_coverage(path: str) -> pd.DataFrame:
    """
    Computes:

        organization -> number of distinct visited websites

    Uses union of websites rather than summing domain counts,
    preventing Google properties from being double-counted.
    """

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    org_sites = defaultdict(set)

    for cookie_entries in data.values():

        for entry in cookie_entries:

            reader = entry.get("reader_domain")
            site = entry.get("visited_domain")

            if not reader or not site:
                continue

            org = ORG_MAP.get(reader, "Other")

            org_sites[org].add(site)

    rows = [
        {
            "organization": org,
            "site_count": len(sites),
        }
        for org, sites in org_sites.items()
    ]

    return pd.DataFrame(rows)


# ------------------------------------------------------------------
# Plot
# ------------------------------------------------------------------

def plot_organization_coverage(df: pd.DataFrame):

    apply_theme()

    # Remove "Other"
    df = df[df["organization"] != "Other"]

    top = (
        df.sort_values("site_count", ascending=False)
        .head(15)
        .sort_values("site_count")
    )

    fig, ax = plt.subplots(figsize=(10, 7))

    colors = [
        COLORS[i % len(COLORS)]
        for i in range(len(top))
    ]

    bars = ax.barh(
        top["organization"],
        top["site_count"],
        color=colors,
    )

    ax.set_title(
        "Organizations Performing Third-Party Cookie Reads"
    )

    ax.set_xlabel("Distinct Websites")

    ax.set_ylabel("Organization")

    ax.grid(axis="x", alpha=0.3)

    for bar in bars:

        width = bar.get_width()

        ax.text(
            width,
            bar.get_y() + bar.get_height() / 2,
            f" {int(width)}",
            va="center",
        )

    plt.tight_layout()

    save_figure(
        OUT_DIR,
        "organization_cookie_readers.png",
        "organization_cookie_readers.pdf",
    )


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

if __name__ == "__main__":

    df = load_organization_coverage(INPUT_FILE)

    print(
        df.sort_values(
            "site_count",
            ascending=False,
        )
    )

    plot_organization_coverage(df)