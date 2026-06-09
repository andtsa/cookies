"""
scripts/find_cookie_syncing.py
------------------------------
Report *cookie syncing* — trackers sharing a user identifier with one another by
passing a cookie's value to a different domain through request parameters.

This is a thin reporting CLI over the central annotation engine: detection lives
in :mod:`analysis.src.syncing` and is reached through
:meth:`analysis.CookieDataset.syncing`, which computes (and caches on disk via
``annotate.py`` / ``.analysis_cache``) sync events for the whole crawl. There is
no longer an in-place ``--annotate`` step — the engine cache is the single source
of truth and the plot scripts read from it directly.

Three layers of evidence (per the agreed design):

  PRIMARY (confirmed)
      A cookie value observed on the site (and its URL-/base64-encoded forms in
      ``--deep`` mode) appears as a query-parameter value in a request sent to a
      *different registered domain*. Direct proof an identifier crossed a domain.

  SECONDARY (candidate)
      A cross-domain query-parameter value is high-entropy and long enough to
      look like a UID, even though it was not matched to a known cookie.

  PATH (endpoint heuristic)
      A cross-domain request that already carries an identifier (a confirmed or
      candidate row) also hits a known sync-endpoint keyword in its URL path or a
      query-parameter *name* (e.g. /usersync, partner_uid). It annotates those
      rows with a ``path_sync`` field rather than forming a separate population.

Usage
-----
    python scripts/find_cookie_syncing.py cookies_data
    python scripts/find_cookie_syncing.py cookies_data --min-bits 36
    python scripts/find_cookie_syncing.py cookies_data --deep-match    # base64 + embedded
    python scripts/find_cookie_syncing.py cookies_data --no-path-match # skip endpoint heuristic
    python scripts/find_cookie_syncing.py cookies_data --out syncs.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from analysis import CookieDataset  # noqa: E402


def print_report(events: list[dict], total_sites: int) -> None:
    pair_counter: Counter = Counter()
    path_pair_counter: Counter = Counter()
    total_confirmed = 0
    total_candidates = 0
    total_substring = 0
    total_path = 0
    total_path_excl = 0
    sites_with_sync = 0
    sites_with_path = 0

    for entry in events:
        confirmed = entry["confirmed"]
        candidates = entry["candidates"]
        site_domain = entry["site_domain"]
        if confirmed:
            sites_with_sync += 1
        total_confirmed += len(confirmed)
        total_candidates += len(candidates)
        total_substring += sum(1 for ev in confirmed if ev.get("match") == "substring")
        for ev in confirmed:
            pair_counter[(site_domain, ev["to_domain"])] += 1

        # Path-sync evidence lives as a ``path_sync`` annotation on
        # confirmed/candidate rows; count it per request (dedup across the
        # possibly-many rows of one request) so the totals mean "requests".
        confirmed_urls = {ev["request_url"] for ev in confirmed}
        seen: dict[str, str] = {}  # request_url -> to_domain
        for ev in confirmed + candidates:
            if "path_sync" in ev:
                seen.setdefault(ev["request_url"], ev["to_domain"])
        if seen:
            sites_with_path += 1
        total_path += len(seen)
        for url, to in seen.items():
            if url not in confirmed_urls:
                total_path_excl += 1
            path_pair_counter[(site_domain, to)] += 1

    print(f"\n{'=' * 70}")
    print("  Cookie Syncing Report")
    print(f"  Sites analysed         : {total_sites}")
    print(f"  Sites with confirmed   : {sites_with_sync}")
    print(f"  Confirmed sync events  : {total_confirmed}")
    print(f"    of which embedded    : {total_substring}")
    print(f"  Candidate sync events  : {total_candidates}")
    print(f"  Sites with path-sync   : {sites_with_path}")
    print(f"  Path-sync events       : {total_path}")
    print(f"    excl. of confirmed   : {total_path_excl}")
    print(f"{'=' * 70}\n")

    if pair_counter:
        print("  Top confirmed sync domain pairs (from -> to):")
        for (frm, to), count in pair_counter.most_common(30):
            print(f"    {frm:>30}  ->  {to:<30}  ({count})")
        print()

    if path_pair_counter:
        print("  Top sync-endpoint domain pairs (from -> to):")
        for (frm, to), count in path_pair_counter.most_common(30):
            print(f"    {frm:>30}  ->  {to:<30}  ({count})")
        print()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Report cookie syncing from a crawl, via the analysis engine.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("data_dir", help="Crawl data directory (e.g. cookies_data).")
    p.add_argument(
        "--min-bits",
        type=float,
        default=None,
        help="total_bits cutoff for high-entropy candidate params "
        "(default: the dataset's sync_min_bits).",
    )
    p.add_argument(
        "--deep-match",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Also match base64-encoded and embedded (substring) cookie values.",
    )
    p.add_argument(
        "--path-match",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Annotate identifier rows that also hit a sync endpoint "
        "(URL path / param name).",
    )
    p.add_argument(
        "--engine",
        default="hyperscan",
        choices=["hyperscan", "re"],
        help="EasyPrivacy matching engine (auto-falls back to re where needed).",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Optional path to write the per-site sync events as JSON.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    kwargs = {"engine": args.engine}
    if args.min_bits is not None:
        kwargs["sync_min_bits"] = args.min_bits
    ds = CookieDataset(args.data_dir, **kwargs)

    total_sites = sum(1 for _ in ds.iter_raw_sites())
    if total_sites == 0:
        print(
            "No site JSON found. Cookie syncing needs a Chromium-family crawl "
            "with the 'requests' field.",
            file=sys.stderr,
        )
        sys.exit(1)

    events = ds.syncing(deep=args.deep_match, path=args.path_match)
    print_report(events, total_sites)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(events, fh, indent=2)
        print(f"Results written to: {args.out}")


if __name__ == "__main__":
    main()
