"""
scripts/cross_reference_sync_reads.py
-------------------------------------
Cross-reference cookie *syncing* with cookie *reading*: for every confirmed sync
of a cookie (its value sent to another domain), find third parties that ALSO
read that same cookie name by JavaScript but were **not** a party to the sync —
i.e. an external collector quietly picking up an identifier that two other
domains were syncing.

Both signals come from the analysis engine and its on-disk cache (warm them once
with ``scripts/annotate.py``):

    * confirmed syncs   -> CookieDataset.syncing()
    * third-party reads -> CookieDataset.third_party_reads()

Outputs (under ``--out``):
    sync_reads_external_readers.json   one row per (synced cookie, external reader)
and prints a short summary of the most active external readers.

Usage
-----
    python scripts/cross_reference_sync_reads.py --data cookies_data
    python scripts/cross_reference_sync_reads.py --data cookies_data --out plots/reads
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from analysis import CookieDataset  # noqa: E402


def build_read_index(ds: CookieDataset) -> dict[str, list[dict]]:
    """cookie_name -> [{reader_domain, reader_script, visited_domain}, ...]."""
    index: dict[str, list[dict]] = defaultdict(list)
    for row in ds.third_party_reads():
        index[row["cookie_name"]].append(
            {
                "reader_domain": row.get("reader_domain"),
                "reader_script": row.get("reader_script"),
                "visited_domain": row.get("visited_domain"),
            }
        )
    return dict(index)


def find_external_readers(ds: CookieDataset) -> list[dict]:
    """External-reader rows: a synced cookie read by a non-sync-party domain."""
    read_index = build_read_index(ds)
    external: list[dict] = []

    for event in ds.syncing():
        site_domain = event.get("site_domain", "")
        for ev in event.get("confirmed", []):
            cookie_name = ev.get("cookie_name")
            if not cookie_name:
                continue
            to_domain = ev.get("to_domain", "")
            parties = {site_domain, to_domain}
            for reader in read_index.get(cookie_name, []):
                reader_domain = reader.get("reader_domain")
                if not reader_domain or reader_domain in parties:
                    continue
                external.append(
                    {
                        "site_domain": site_domain,
                        "cookie_name": cookie_name,
                        "sync_to": to_domain,
                        "reader_domain": reader_domain,
                        "reader_script": reader.get("reader_script"),
                        "visited_domain": reader.get("visited_domain"),
                    }
                )
    return external


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Cross-reference cookie syncing with third-party cookie reads.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--data", default="./cookies_data", help="crawl data directory")
    p.add_argument("--out", default="./plots/reads", help="output directory")
    p.add_argument(
        "--engine",
        default="hyperscan",
        choices=["hyperscan", "re"],
        help="EasyPrivacy matching engine (auto-falls back to re where needed).",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    ds = CookieDataset(args.data, engine=args.engine)

    external = find_external_readers(ds)

    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, "sync_reads_external_readers.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(external, fh, indent=2)

    print(f"Saved -> {out_path}")
    print(f"External reader records: {len(external):,}")
    if external:
        top = Counter(r["reader_domain"] for r in external).most_common(20)
        print("\n  Top external readers of synced cookies:")
        for dom, n in top:
            print(f"    {dom:<40}  {n:>6}")


if __name__ == "__main__":
    main()
