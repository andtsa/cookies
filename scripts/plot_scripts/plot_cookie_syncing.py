"""
Cookie Syncing Ecosystem (directed graph)
Nodes are registered domains; a directed edge A → B means a cookie value set on
a site was sent to domain B as a request parameter (a confirmed sync), where A
is the domain that received/sent it. Edge width encodes how many sync events ran
along that pair. Node size encodes in-degree (how many distinct partners sync
*into* a domain — the "ID collectors"). Domains seen as trackers are highlighted.

Reads the ``cookie_syncing`` field that scripts/find_cookie_syncing.py writes
into each site JSON (run it with --annotate first). Chromium-family data only.

Usage:
    python scripts/plot_scripts/plot_cookie_syncing.py --data cookies_data/chromium --out plots/syncing --top_edges 60
"""

import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict

import matplotlib.pyplot as plt
import networkx as nx

sys.path.insert(0, os.path.dirname(__file__))
from utils import apply_theme, save_figure, BG, DARK, LIGHT, ACCENT, ACCENT2, MID


def _load_sync_edges(data_dir: str):
    """Return (edge_counts, tracker_domains).

    edge_counts: Counter[(from_domain, to_domain)] of confirmed sync events.
    tracker_domains: set of registered domains that set a known-tracker cookie
                     anywhere in the dataset (used to color nodes).
    """
    paths = sorted(glob.glob(os.path.join(data_dir, "**", "*.json"), recursive=True))
    if not paths:
        raise FileNotFoundError(f"No JSON files found in: {data_dir}")

    edge_counts: Counter = Counter()
    tracker_domains: set[str] = set()
    annotated = 0

    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue

        # Collect tracker domains from cookies for node coloring.
        for cookie in data.get("cookies", []):
            it = cookie.get("is_tracker")
            if it:
                dom = (cookie.get("domain") or "").lstrip(".")
                if dom:
                    tracker_domains.add(dom)

        sync = data.get("cookie_syncing")
        if not sync:
            continue
        annotated += 1
        site_domain = sync.get("site_domain", "")
        for ev in sync.get("confirmed", []):
            to_domain = ev.get("to_domain", "")
            if site_domain and to_domain and site_domain != to_domain:
                edge_counts[(site_domain, to_domain)] += 1

    if annotated == 0:
        raise ValueError(
            "No 'cookie_syncing' annotations found. Run "
            "`python scripts/find_cookie_syncing.py <dir> --annotate` first "
            "(needs a Chromium crawl with the 'requests' field)."
        )
    return edge_counts, tracker_domains


def _is_tracker_domain(domain: str, tracker_domains: set[str]) -> bool:
    """True if domain (or a parent) is among the known tracker domains."""
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        if ".".join(parts[i:]) in tracker_domains:
            return True
    return domain in tracker_domains


def plot_cookie_syncing(data_dir: str, out_dir: str, top_edges: int = 60) -> None:
    apply_theme()
    edge_counts, tracker_domains = _load_sync_edges(data_dir)

    if not edge_counts:
        fig, ax = plt.subplots(figsize=(10, 8))
        ax.text(0.5, 0.5, "No confirmed cookie-sync events found",
                ha="center", va="center", transform=ax.transAxes, fontsize=14, color=DARK)
        ax.axis("off")
        save_figure(out_dir, "plot_cookie_syncing.png", "plot_cookie_syncing.pdf")
        return

    # Keep the strongest edges so the graph stays legible.
    top = edge_counts.most_common(top_edges)

    G = nx.DiGraph()
    for (frm, to), w in top:
        G.add_edge(frm, to, weight=w)

    in_deg = dict(G.in_degree())
    node_sizes = [300 + 600 * in_deg.get(n, 0) for n in G.nodes()]
    node_colors = [
        ACCENT if _is_tracker_domain(n, tracker_domains) else MID for n in G.nodes()
    ]

    max_w = max((d["weight"] for *_e, d in G.edges(data=True)), default=1)
    edge_widths = [0.6 + 3.4 * (d["weight"] / max_w) for *_e, d in G.edges(data=True)]

    pos = nx.spring_layout(G, k=0.8, seed=42, iterations=120)

    fig, ax = plt.subplots(figsize=(14, 11))
    nx.draw_networkx_edges(
        G, pos, ax=ax, width=edge_widths, edge_color=DARK, alpha=0.45,
        arrows=True, arrowsize=12, arrowstyle="-|>",
        connectionstyle="arc3,rad=0.08", node_size=node_sizes,
    )
    nx.draw_networkx_nodes(
        G, pos, ax=ax, node_size=node_sizes, node_color=node_colors,
        edgecolors=BG, linewidths=1.0,
    )
    # Label only the more connected nodes to avoid clutter.
    deg_all = {n: G.degree(n) for n in G.nodes()}
    label_nodes = {
        n: n for n in G.nodes()
        if deg_all[n] >= 2 or in_deg.get(n, 0) >= 1
    }
    nx.draw_networkx_labels(G, pos, labels=label_nodes, ax=ax, font_size=8, font_color=DARK)

    from matplotlib.patches import Patch

    ax.legend(
        handles=[
            Patch(facecolor=ACCENT, label="Known tracker domain"),
            Patch(facecolor=MID, label="Other domain"),
        ],
        loc="upper left",
        fontsize=11,
    )
    ax.set_title(
        f"Cookie Syncing Ecosystem  (top {len(top)} domain pairs)",
        fontsize=18, fontweight="bold", pad=16,
    )
    ax.axis("off")
    plt.tight_layout()
    save_figure(out_dir, "plot_cookie_syncing.png", "plot_cookie_syncing.pdf")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data/chromium")
    parser.add_argument("--out", default="./plots/syncing")
    parser.add_argument("--top_edges", default=60, type=int)
    args = parser.parse_args()
    plot_cookie_syncing(args.data, args.out, args.top_edges)
