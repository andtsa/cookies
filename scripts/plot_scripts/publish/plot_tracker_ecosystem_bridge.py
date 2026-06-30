"""
Tracker Ecosystem Bridge Graph.

Visualises third-party trackers that appear on both health and non-health
websites. Trackers are ranked by their presence across the two ecosystems
(H × NH), where H is the number of health sites and NH is the number of
non-health sites containing the tracker.

Trackers use the unified, classification-based ``is_tracker`` from
``CookieDataset.classified_cookies`` (``tracker_tier >= "probable"``) — the same
definition every other figure uses — so the graph captures behaviourally
detected trackers, not just filter-list matches.

The analysis can be filtered by country and browser and exports both cream and
white themed PNG/PDF figures. The dataset goes through the cached ``dataset()``
factory, so it is rank-capped (see ``COOKIE_RANK_CAP``) and reuses the warmed
annotation cache.
"""

import argparse
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np

from scripts.plot_scripts.utils import *

COMPANY_NAMES = {
    "demdex.net": "Adobe",
    "hs-analytics.net": "HubSpot",
    "media.net": "Media.net",
    "sc-static.net": "Snapchat",
    "criteo.com": "Criteo",
    "tapad.com": "Tapad",
    "hsadspixel.net": "HubSpot Ads",
    "aim-tag.hcn.health": "HCN Health",
    "ct.pinterest.com": "Pinterest",
    "evergage.com": "Salesforce",
    "everesttech.net": "Adobe Everest",
    "mc.yandex.com": "Yandex",
    "mc.yandex.ru": "Yandex",
    "yandex.com": "Yandex",
    "yandex.ru": "Yandex",
    "bidr.io": "Beeswax",
    "m.stripe.com": "Stripe",
    "doubleclick.net": "Google DoubleClick",
    "google-analytics.com": "Google Analytics",
    "facebook.com": "Meta",
    "adnxs.com": "Microsoft Xandr",
    "rubiconproject.com": "Magnite",
    "pubmatic.com": "PubMatic",
    "openx.net": "OpenX",
    "casalemedia.com": "Index Exchange",
    "rlcdn.com": "LiveRamp",
    "bluekai.com": "Oracle BlueKai",
    "krxd.net": "Salesforce Krux",
    "quantserve.com": "Quantcast",
    "nr-data.net": "New Relic",
    "px.mountain.com": "MNTN",
}


def looks_like_first_party(provider) -> bool:
    """True for bare (single-label) providers that aren't real third parties."""
    return "." not in str(provider).lstrip(".")


def build_bridge_stats(cookies, health_domains, top_n=15):
    """Return the top ``top_n`` ``(company, H, NH, score)`` bridge trackers.

    ``H``/``NH`` are the number of distinct health / non-health sites each
    company's trackers appear on; ``score = H * NH``. Only companies present in
    *both* ecosystems are returned.
    """
    # Site identity for health matching: the path-derived slug, de-slugified
    # back to a real domain (11467_com -> 11467.com).
    cookies = cookies.copy()
    cookies["site_domain"] = (
        cookies["domain"]
        .astype(str)
        .str.lstrip(".")
        .str.lower()
        .str.replace("_", ".")
        .str.removeprefix("www.")
    )

    trackers = cookies[cookies["is_tracker"].astype(bool)].copy()
    print(f"Tracker rows: {len(trackers):,}")

    # Provider = canonical tracker provider, falling back to the cookie's own
    # registered domain when the list didn't attribute one.
    trackers["_provider"] = trackers["tracker_provider"].fillna(
        trackers["cookie_domain"].astype(str).str.lstrip(".")
    )
    trackers = trackers[~trackers["_provider"].apply(looks_like_first_party)]

    connections = (
        trackers[["_provider", "site_domain"]]
        .dropna(subset=["_provider", "site_domain"])
        .drop_duplicates()
    )
    connections["is_health"] = connections["site_domain"].isin(health_domains)
    print("\nHealth classification:")
    print(connections["is_health"].value_counts())

    health_counts = (
        connections[connections["is_health"]]
        .groupby("_provider")["site_domain"]
        .nunique()
    )
    nonhealth_counts = (
        connections[~connections["is_health"]]
        .groupby("_provider")["site_domain"]
        .nunique()
    )

    company_stats: dict[str, dict[str, int]] = {}
    for tracker in set(health_counts.index) | set(nonhealth_counts.index):
        h = int(health_counts.get(tracker, 0))
        n = int(nonhealth_counts.get(tracker, 0))
        if h == 0 and n == 0:
            continue
        company = COMPANY_NAMES.get(str(tracker).strip().lower().lstrip("."), tracker)
        stats = company_stats.setdefault(company, {"health": 0, "nonhealth": 0})
        stats["health"] += h
        stats["nonhealth"] += n

    interesting = [
        (company, s["health"], s["nonhealth"], s["health"] * s["nonhealth"])
        for company, s in company_stats.items()
        if s["health"] > 0 and s["nonhealth"] > 0
    ]
    interesting.sort(key=lambda x: x[3], reverse=True)
    interesting = interesting[:top_n]

    print("\nTop bridge organizations:\n")
    for company, h, n, score in interesting:
        print(f"{company:25s}H={h:4d} NH={n:5d} Score={score:10d}")

    return interesting


def build_graph(interesting):
    G = nx.Graph()
    health_node, nonhealth_node = "Health\nSites", "Non-Health\nSites"
    G.add_node(health_node)
    G.add_node(nonhealth_node)
    for company, h, n, _ in interesting:
        G.add_node(company)
        if h > 0:
            G.add_edge(health_node, company, weight=h)
        if n > 0:
            G.add_edge(company, nonhealth_node, weight=n)

    pos = {health_node: (-4, 0), nonhealth_node: (4, 0)}
    for i, (company, *_rest) in enumerate(interesting):
        y = ((len(interesting) - 1) / 2 - i) * 1.2
        pos[company] = (0, y)
    return G, pos, health_node, nonhealth_node


def draw(interesting, country, browser, bg):
    apply_theme()
    if bg == "white":
        plt.rcParams.update(
            {
                "figure.facecolor": "white",
                "axes.facecolor": "white",
                "savefig.facecolor": "white",
                "text.color": "#222222",
                "axes.titlecolor": "#222222",
            }
        )

    G, pos, health_node, nonhealth_node = build_graph(interesting)
    fig, ax = plt.subplots(figsize=(11, 8))

    edge_widths = [
        max(1.0, np.sqrt(data["weight"])) for _, _, data in G.edges(data=True)
    ]
    health_color, nonhealth_color, tracker_color = (
        BUCKET_COLORS[0],
        BUCKET_COLORS[1],
        MID,
    )

    nx.draw_networkx_edges(G, pos, width=edge_widths, edge_color=MID, alpha=0.30, ax=ax)
    nx.draw_networkx_nodes(
        G,
        pos,
        nodelist=[health_node],
        node_color=health_color,
        node_size=3200,
        alpha=0.90,
        ax=ax,
    )
    nx.draw_networkx_nodes(
        G,
        pos,
        nodelist=[nonhealth_node],
        node_color=nonhealth_color,
        node_size=3200,
        alpha=0.90,
        ax=ax,
    )
    tracker_sizes = [400 + np.sqrt(h + n) * 80 for _, h, n, _ in interesting]
    nx.draw_networkx_nodes(
        G,
        pos,
        nodelist=[t[0] for t in interesting],
        node_color=tracker_color,
        node_size=tracker_sizes,
        alpha=0.85,
        ax=ax,
    )

    labels = {health_node: "Health Sites", nonhealth_node: "Non-Health Sites"}
    for company, h, n, _ in interesting:
        labels[company] = f"{company}\nH={h} | NH={n}"
    nx.draw_networkx_labels(G, pos, labels, font_size=8, ax=ax)

    ax.set_title(
        f"Tracker Presence on Health vs Non-Health Websites\n{country} · {browser}"
    )
    ax.axis("off")
    plt.tight_layout()
    return fig


def plot_tracker_bridge(data_dir, health_csv, country, browser, top_n, out_dir):
    apply_theme()
    health_domains = load_health_domains(health_csv)
    print(f"Loaded {len(health_domains):,} health domains")

    ds = dataset(data_dir)
    cookies = filter_country_browser(ds.classified_cookies, country, browser)
    print(f"After filter [{country} / {browser}]: {len(cookies):,} cookie rows")
    if cookies.empty:
        raise SystemExit(
            f"No cookies for country={country!r} browser={browser!r}. "
            "Check the values (use --country all / --browser all to widen)."
        )

    interesting = build_bridge_stats(cookies, health_domains, top_n=top_n)
    if not interesting:
        raise SystemExit("No trackers bridge both ecosystems for this filter.")

    os.makedirs(out_dir, exist_ok=True)
    stem = f"tracker_ecosystem_bridge_{country}_{browser}"

    draw(interesting, country, browser, bg="cream")
    save_figure(out_dir, f"{stem}.png", f"{stem}.pdf", facecolor=BG)

    draw(interesting, country, browser, bg="white")
    save_figure(out_dir, f"{stem}_white.png", f"{stem}_white.pdf", facecolor="white")


def main():
    parser = argparse.ArgumentParser(
        description="Bridge tracker graph: health vs non-health sites"
    )
    parser.add_argument("--data", default=os.path.join(ROOT, "cookies_data"))
    parser.add_argument(
        "--health", default=os.path.join(ROOT, "health_websites_1K.csv")
    )
    parser.add_argument(
        "--country",
        default="Netherlands",
        help="Country to filter on, or 'all' (default: Netherlands)",
    )
    parser.add_argument(
        "--browser",
        default="chromium",
        help="Browser to filter on, or 'all' (default: chromium)",
    )
    parser.add_argument("--top_n", type=int, default=15)
    parser.add_argument(
        "--out",
        default=os.path.join(ROOT, "plots", "tracker_bridge"),
        help="Output directory for saved figures",
    )
    args = parser.parse_args()

    plot_tracker_bridge(
        data_dir=args.data,
        health_csv=args.health,
        country=args.country,
        browser=args.browser,
        top_n=args.top_n,
        out_dir=args.out,
    )


if __name__ == "__main__":
    main()
