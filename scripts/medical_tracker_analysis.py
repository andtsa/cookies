"""
scripts/medical_tracker_analysis.py
-----------------------------------
Cross-reference known trackers against the *health/medical* website list: for
every tracker observed on a crawled site, record whether that site is a health
site, then summarise each tracker provider by how many health vs non-health
sites it appears on.

Reads the crawl through the analysis engine (``CookieDataset``); the per-cookie
``domain`` column is the *crawled site* domain (frames.py), and ``is_tracker`` /
``tracker_provider`` are the engine's tracker labels. The health site list is the
repo's ``list_websites_health.csv`` (columns ``rank,url``).

Outputs (written next to the repo root):
    medical_tracker_connections_FULL.csv   one row per (provider, site, is_health)
    medical_tracker_summary.csv            per-provider health/non-health counts

Usage:
    python scripts/medical_tracker_analysis.py
    python scripts/medical_tracker_analysis.py --data cookies_data --health list_websites_health.csv
"""

import argparse
import os
import sys

import pandas as pd

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from analysis import CookieDataset  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", default="cookies_data", help="crawl data directory")
    p.add_argument(
        "--health",
        default="list_websites_health.csv",
        help="health website list (columns: rank,url)",
    )
    p.add_argument(
        "--out-dir",
        default=ROOT,
        help="directory to write the two output CSVs into",
    )
    return p.parse_args()


def _resolve(path: str) -> str:
    """Resolve a path against the repo root when it is not already absolute."""
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


def main() -> None:
    args = parse_args()

    # --------------------------------------------------
    # Load health domains
    # --------------------------------------------------
    health_csv = _resolve(args.health)
    health_domains = set(pd.read_csv(health_csv)["url"].astype(str).str.lower())
    print(f"Loaded {len(health_domains):,} health domains")

    # --------------------------------------------------
    # Load full dataset
    # --------------------------------------------------
    ds = CookieDataset(
        _resolve(args.data),
        n_workers=max(1, (os.cpu_count() or 8) - 1),
    )

    cookies = ds.cookies.copy()
    cookies["domain"] = cookies["domain"].astype(str).str.lower()
    print(f"Loaded {len(cookies):,} cookie rows")

    # --------------------------------------------------
    # Tracker cookies only
    # --------------------------------------------------
    trackers = cookies[cookies["is_tracker"].astype(bool)].copy()
    print(f"Tracker rows: {len(trackers):,}")

    provider_col = "tracker_provider"

    # --------------------------------------------------
    # Mark health / non-health
    # --------------------------------------------------
    trackers["is_health"] = trackers["domain"].isin(health_domains)

    # --------------------------------------------------
    # BIG connection table — one row = tracker observed on website
    # --------------------------------------------------
    connections = (
        trackers[[provider_col, "domain", "is_health"]]
        .dropna(subset=[provider_col])
        .drop_duplicates()
    )

    os.makedirs(args.out_dir, exist_ok=True)
    conn_path = os.path.join(args.out_dir, "medical_tracker_connections_FULL.csv")
    connections.to_csv(conn_path, index=False)
    print(f"Saved {len(connections):,} rows to {conn_path}")

    # --------------------------------------------------
    # Summary table
    # --------------------------------------------------
    health_counts = (
        connections[connections["is_health"]]
        .groupby(provider_col)["domain"]
        .nunique()
        .reset_index(name="health_sites")
    )
    non_health_counts = (
        connections[~connections["is_health"]]
        .groupby(provider_col)["domain"]
        .nunique()
        .reset_index(name="non_health_sites")
    )

    summary = health_counts.merge(
        non_health_counts, on=provider_col, how="outer"
    ).fillna(0)
    summary["total_sites"] = summary["health_sites"] + summary["non_health_sites"]
    summary["non_health_fraction"] = (
        summary["non_health_sites"] / summary["total_sites"]
    )
    summary = summary.sort_values("health_sites", ascending=False)

    summary_path = os.path.join(args.out_dir, "medical_tracker_summary.csv")
    summary.to_csv(summary_path, index=False)

    print("\nTop 20 trackers on health sites:\n")
    print(summary.head(20).to_string(index=False))
    print(f"\nSaved {summary_path}")


if __name__ == "__main__":
    main()
