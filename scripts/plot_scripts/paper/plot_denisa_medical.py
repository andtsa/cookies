"""
Tracker Ecosystem Bridge Graph.

Visualises third-party trackers that appear on both health and non-health
websites. Trackers are ranked by their presence across the two ecosystems
(H × NH), where H is the number of health sites and NH is the number of
non-health sites containing the tracker.

The analysis can be filtered by country and browser and exports both cream
and white themed PNG/PDF figures.
"""
import os
import sys
import argparse

import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    dataset,
    save_figure,
    BG,
    DARK,
    MID,
    BUCKET_COLORS,
)

HEALTH_CSV = "health_websites_1K.csv"
DATA_DIR = "cookies_data"

def looks_like_first_party(provider):
    return "." not in str(provider).lstrip(".")


def plot_tracker_bridge(country: str, browser: str, out_dir: str):

    apply_theme()
    health_domains = set(
        pd.read_csv(HEALTH_CSV)["domain"]
        .astype(str)
        .str.lower()
        .str.removeprefix("www.")
    )

    print(f"Loaded {len(health_domains):,} health domains")

    ds = dataset(DATA_DIR)
    cookies = ds.cookies.copy()

    if "country" in cookies.columns:
        cookies = cookies[
            cookies["country"].str.lower() == country.lower()
        ]

    if "browser" in cookies.columns:
        cookies = cookies[
            cookies["browser"].str.lower() == browser.lower()
        ]

    print(
        f"After filter [{country} / {browser}]: "
        f"{len(cookies):,} cookie rows"
    )


    domain_col = "bare_domain" if "bare_domain" in cookies.columns else "domain"

    cookies[domain_col] = (
        cookies[domain_col]
        .astype(str)
        .str.lstrip(".")
        .str.lower()
        .str.replace("_", ".")
        .str.removeprefix("www.")
    )

    trackers = cookies[
        cookies["is_tracker_bool"].astype(bool)
    ].copy()

    print(trackers.columns.tolist())
    print(f"Tracker rows: {len(trackers):,}")
    cookie_domain_col = "domain" if "domain" in trackers.columns else domain_col

    trackers["_provider"] = (
        trackers["tracker_provider"]
        .fillna(
            trackers[cookie_domain_col]
            .astype(str)
            .str.lstrip(".")
        )
    )

    trackers = trackers[
        ~trackers["_provider"].apply(looks_like_first_party)
    ]

    connections = (
        trackers[["_provider", domain_col]]
        .dropna(subset=["_provider", domain_col])
        .drop_duplicates()
    )

    connections["is_health"] = connections[domain_col].isin(health_domains)

    print("\nHealth classification:")
    print(connections["is_health"].value_counts())
    health_counts = (
        connections[connections["is_health"]]
        .groupby("_provider")[domain_col]
        .nunique()
    )

    nonhealth_counts = (
        connections[~connections["is_health"]]
        .groupby("_provider")[domain_col]
        .nunique()
    )

    all_trackers = set(health_counts.index) | set(nonhealth_counts.index)

    interesting_trackers = []

    for tracker in all_trackers:

        h = int(health_counts.get(tracker, 0))
        n = int(nonhealth_counts.get(tracker, 0))

        if h > 0 and n > 0:

            score = h * n

            interesting_trackers.append(
                (tracker, h, n, score)
            )

    interesting_trackers = sorted(
        interesting_trackers,
        key=lambda x: x[3],
        reverse=True
    )[:15]


    print("\nTop bridge trackers:\n")

    for tracker, h, n, score in interesting_trackers:

        print(
            f"{tracker:25s}"
            f"H={h:4d} "
            f"NH={n:5d} "
            f"Score={score:10d}"
        )
    G = nx.Graph()

    HEALTH_NODE = "Health\nSites"
    NONHEALTH_NODE = "Non-Health\nSites"

    G.add_node(HEALTH_NODE)
    G.add_node(NONHEALTH_NODE)

    for company, h, n, score in interesting_trackers:
        G.add_node(company)
        if h > 0:
            G.add_edge(HEALTH_NODE, company, weight=h)
        if n > 0:
            G.add_edge(company, NONHEALTH_NODE, weight=n)

    pos = {
        HEALTH_NODE: (-4, 0),
        NONHEALTH_NODE: (4, 0)
    }

    for i, (company, _, _, _) in enumerate(interesting_trackers):
        y = ((len(interesting_trackers) - 1) / 2 - i) * 1.2
        pos[company] = (0, y)

    def draw(bg: str):
        apply_theme()
        if bg == "white":
            plt.rcParams.update({
                "figure.facecolor": "white",
                "axes.facecolor":   "white",
                "savefig.facecolor": "white",
                "text.color": "#222222",
                "axes.titlecolor": "#222222",
            })

        fig, ax = plt.subplots(figsize=(11, 8))

        edge_widths = [
            max(1.0, np.sqrt(data["weight"]))
            for _, _, data in G.edges(data=True)
        ]

        HEALTH_COLOR    = BUCKET_COLORS[0]
        NONHEALTH_COLOR = BUCKET_COLORS[1]
        TRACKER_COLOR   = MID

        nx.draw_networkx_edges(
            G, pos,
            width=edge_widths,
            edge_color=MID,
            alpha=0.30,
            ax=ax,
        )

        nx.draw_networkx_nodes(
            G, pos,
            nodelist=[HEALTH_NODE],
            node_color=HEALTH_COLOR,
            node_size=3200,
            alpha=0.90,
            ax=ax,
        )

        nx.draw_networkx_nodes(
            G, pos,
            nodelist=[NONHEALTH_NODE],
            node_color=NONHEALTH_COLOR,
            node_size=3200,
            alpha=0.90,
            ax=ax,
        )

        tracker_sizes = [
            400 + np.sqrt(h + n) * 80
            for _, h, n, _ in interesting_trackers
        ]

        nx.draw_networkx_nodes(
            G, pos,
            nodelist=[t[0] for t in interesting_trackers],
            node_color=TRACKER_COLOR,
            node_size=tracker_sizes,
            alpha=0.85,
            ax=ax,
        )
        

        labels = {
            HEALTH_NODE:    "Health Sites",
            NONHEALTH_NODE: "Non-Health Sites",
        }
        for company, h, n, score in interesting_trackers:

            labels[company] = (
                f"{company}\n"
                f"H={h} | NH={n}"
            )

        nx.draw_networkx_labels(G, pos, labels, font_size=8, ax=ax)

        ax.set_title(
            f"Tracker Presence on Health vs Non-Health Websites\n"
            f"{country} · {browser}"
        )
        ax.axis("off")
        plt.tight_layout()
        return fig

    os.makedirs(out_dir, exist_ok=True)
    stem = f"tracker_ecosystem_bridge_{country}_{browser}"

    draw(bg="cream")
    save_figure(
        out_dir,
        f"{stem}.png",
        f"{stem}.pdf",
        facecolor=BG,
    )

    draw(bg="white")
    save_figure(
        out_dir,
        f"{stem}_white.png",
        f"{stem}_white.pdf",
        facecolor="white",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Bridge tracker graph: health vs non-health sites"
    )
    parser.add_argument(
        "--country",  default="Netherlands",
        help="Country to filter on (default: Netherlands)"
    )
    parser.add_argument(
        "--browser",  default="chromium",
        help="Browser to filter on (default: chromium)"
    )
    parser.add_argument(
        "--out", default=".",
        help="Output directory for saved figures"
    )
    args = parser.parse_args()

    plot_tracker_bridge(
        country=args.country,
        browser=args.browser,
        out_dir=args.out,
    )
