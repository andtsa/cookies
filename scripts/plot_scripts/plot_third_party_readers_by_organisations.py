"""
Organizations Performing Third-Party Cookie Reads

Rolls the reader domains up to their parent organization (Google properties,
Meta, Microsoft, …) and ranks organizations by the number of distinct
first-party websites on which any of their domains read cookies. Coverage is a
*union* of websites per organization, so Google's many properties are not
double-counted.

Reader rows come from the analysis engine
(:meth:`analysis.CookieDataset.third_party_reads`, cached by scripts/annotate.py).

Usage:
    python scripts/plot_scripts/plot_third_party_readers_by_organisations.py --data cookies_data --out plots/reads --top_n 15
"""

import os
import sys
from collections import defaultdict

import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    dataset,
    save_figure,
    make_parser,
    hbar_chart,
    annotate_hbars,
    gradient_colors,
    DARK,
)

# Reader domain -> parent organization.
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


def organization_coverage(data_dir: str) -> list[tuple[str, int]]:
    """Return ``[(organization, distinct_site_count), ...]`` descending.

    Only mapped (known) organizations are kept; unmapped readers are dropped so
    the chart shows named organizations rather than a giant "Other" bar.
    """
    org_sites: dict[str, set] = defaultdict(set)
    for row in dataset(data_dir).third_party_reads():
        reader = row.get("reader_domain")
        site = row.get("visited_domain")
        if not reader or not site:
            continue
        org = ORG_MAP.get(reader)
        if org is None:
            continue
        org_sites[org].add(site)
    pairs = [(o, len(sites)) for o, sites in org_sites.items()]
    pairs.sort(key=lambda p: p[1], reverse=True)
    return pairs


def plot_organization_coverage(data_dir: str, out_dir: str, top_n: int = 15) -> None:
    apply_theme()
    pairs = organization_coverage(data_dir)

    fig, ax = plt.subplots(figsize=(10, 7))
    if not pairs:
        ax.text(
            0.5,
            0.5,
            "No third-party cookie reads from known organizations",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=14,
            color=DARK,
        )
        ax.axis("off")
        save_figure(
            out_dir,
            "organization_cookie_readers.png",
            "organization_cookie_readers.pdf",
        )
        return

    top = pairs[:top_n]
    labels = [o for o, _ in top]
    values = [c for _, c in top]

    bars = hbar_chart(ax, labels, values, colors=gradient_colors(values))
    annotate_hbars(ax, bars, [f"{v:,}" for v in values])
    ax.set_title("Organizations Performing Third-Party Cookie Reads")
    ax.set_xlabel("Distinct websites")
    ax.set_ylabel("Organization")
    ax.grid(axis="x", alpha=0.3)
    plt.tight_layout()
    save_figure(
        out_dir, "organization_cookie_readers.png", "organization_cookie_readers.pdf"
    )


if __name__ == "__main__":
    parser = make_parser(__doc__, data="./cookies_data", out="./plots/reads")
    parser.add_argument("--top_n", type=int, default=15)
    args = parser.parse_args()
    plot_organization_coverage(args.data, args.out, args.top_n)
