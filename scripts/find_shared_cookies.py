"""
find_shared_cookies.py
----------------------
Scans a cookies_data/ directory (produced by scripts/get_cookies.py) and
reports every (name, md5_value) pair that appears on more than one website.

Usage
-----
    python find_shared_cookies.py                        # default: ../cookies_data
    python find_shared_cookies.py --data cookies_data
    python find_shared_cookies.py --data cookies_data --min-sites 3
    python find_shared_cookies.py --data cookies_data --out shared_cookies.json
    python find_shared_cookies.py --data cookies_data --trackers-only

Output
------
  Prints a summary table to stdout.
  Optionally writes a JSON report with --out.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def load_cookies_dir(data_dir: str) -> dict[tuple[str, str], list[dict]]:
    """
    Walk every .json file in data_dir and build an index keyed by
    (cookie_name, md5_value) -> list of occurrence dicts.

    Each occurrence dict contains:
        site        – target_url from the file
        source_file – the filename
        domain      – cookie domain field
        cookie_type – "session" or "persistent"
        is_tracker  – raw is_tracker value from the record
    """
    index: dict[tuple[str, str], list[dict]] = defaultdict(list)

    json_files = sorted(Path(data_dir).glob("*.json"))
    if not json_files:
        print(f"[!] No .json files found in '{data_dir}'.", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Loading {len(json_files)} file(s) from '{data_dir}' …")

    for path in json_files:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[!] Skipping {path.name}: {exc}", file=sys.stderr)
            continue

        site = data.get("target_url") or path.stem
        cookies = data.get("cookies", [])

        for cookie in cookies:
            name = cookie.get("name", "")
            md5 = cookie.get("md5_value", "")

            if not name or not md5:
                continue

            index[(name, md5)].append(
                {
                    "site": site,
                    "source_file": path.name,
                    "domain": cookie.get("domain", ""),
                    "cookie_type": cookie.get("cookie_type", ""),
                    "is_tracker": cookie.get("is_tracker", False),
                }
            )

    return index


def find_shared(
    index: dict[tuple[str, str], list[dict]],
    min_sites: int = 2,
    trackers_only: bool = False,
) -> list[dict]:
    """
    Filter the index down to cookies that appear on at least min_sites
    distinct sites, optionally restricting to tracker cookies.

    Returns a list of result dicts sorted by descending site count.
    """
    results = []

    for (name, md5), occurrences in index.items():
        # Deduplicate by site so one site with multiple matching cookies
        # doesn't inflate the count.
        sites_seen: dict[str, dict] = {}
        for occ in occurrences:
            site = occ["site"]
            if site not in sites_seen:
                sites_seen[site] = occ

        if len(sites_seen) < min_sites:
            continue

        if trackers_only:
            # Keep only if at least one occurrence is flagged as a tracker
            if not any(bool(occ.get("is_tracker")) for occ in sites_seen.values()):
                continue

        # Collect unique domains the cookie appears under
        domains = sorted({occ["domain"] for occ in sites_seen.values()})

        # Is this cookie a tracker on *any* of the sites?
        any_tracker = any(bool(occ.get("is_tracker")) for occ in sites_seen.values())

        results.append(
            {
                "name": name,
                "md5_value": md5,
                "site_count": len(sites_seen),
                "domains": domains,
                "any_tracker": any_tracker,
                "sites": [
                    {
                        "site": occ["site"],
                        "source_file": occ["source_file"],
                        "domain": occ["domain"],
                        "cookie_type": occ["cookie_type"],
                        "is_tracker": occ["is_tracker"],
                    }
                    for occ in sorted(sites_seen.values(), key=lambda x: x["site"])
                ],
            }
        )

    results.sort(key=lambda r: r["site_count"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_report(results: list[dict], min_sites: int) -> None:
    if not results:
        print(f"\n[*] No cookies found on {min_sites}+ sites with matching name & md5.")
        return

    total_unique = len(results)
    tracker_count = sum(1 for r in results if r["any_tracker"])

    print(f"\n{'='*70}")
    print(f"  Shared cookies (name + md5 match across ≥{min_sites} sites)")
    print(
        f"  Found {total_unique} unique (name, md5) pair(s) — "
        f"{tracker_count} involve a tracker cookie"
    )
    print(f"{'='*70}\n")

    for i, r in enumerate(results, 1):
        tracker_label = " [known tracker]" if r["any_tracker"] else ""
        print(f"  #{i:>4}  {r['name']!r}{tracker_label}")
        print(f"         md5       : {r['md5_value']}")
        print(f"         site count: {r['site_count']}")
        print(f"         domains   : {', '.join(r['domains'])}")
        print(f"         sites     :")
        for s in r["sites"]:
            tracker_flag = " <- flagged as tracker here" if s["is_tracker"] else ""
            print(
                f"                     {s['site']}  ({s['cookie_type']}){tracker_flag}"
            )
        print()


def write_json(results: list[dict], out_path: str) -> None:
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    print(f"[*] JSON report written to: {out_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find cookies with the same name + md5 hash across multiple crawled sites.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--data",
        default="../cookies_data",
        metavar="DIR",
        help="Directory containing the raw cookie JSON files.",
    )
    parser.add_argument(
        "--min-sites",
        type=int,
        default=2,
        metavar="N",
        help="Minimum number of distinct sites a (name, md5) pair must appear on.",
    )
    parser.add_argument(
        "--trackers-only",
        action="store_true",
        default=False,
        help="Only report cookies flagged as trackers on at least one site.",
    )
    parser.add_argument(
        "--out",
        metavar="FILE",
        default=None,
        help="Optional path to write a JSON report (e.g. shared_cookies.json).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not os.path.isdir(args.data):
        print(f"[!] Directory not found: '{args.data}'", file=sys.stderr)
        sys.exit(1)

    index = load_cookies_dir(args.data)
    results = find_shared(
        index, min_sites=args.min_sites, trackers_only=args.trackers_only
    )

    print_report(results, args.min_sites)

    if args.out:
        write_json(results, args.out)


if __name__ == "__main__":
    main()
