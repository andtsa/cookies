"""
find_shared_cookies.py
----------------------
Scans a directory of *processed* cookie JSON files (produced by
scripts/process_cookies.py) and reports cookies that appear on more than one
website — the empirical signal of cross-site ID persistence.

Three matching strategies are available (``--match-mode``):

  name-md5        (default)  Group by (cookie name, md5 of value). Exact, fast.
  value-entropy              Group high-entropy values by md5 alone, regardless
                             of cookie name. Catches the *same UID* surfacing
                             under different names across sites.
  name-cluster               Group by (name family, md5 of value), where the
                             family is computed with fuzzy name clustering
                             (client/trackers/name_similarity). Catches
                             per-instance name variants (_ga, _gat_UA-…, …).

Because the input is processed JSON, every occurrence carries ``party_type``;
results are always annotated with per-site party info and a
``distinct_first_parties`` count. Use ``--third-party-only`` to keep only
cookies that appear in a third-party context on at least one site (the strong
tracker signal).

Usage
-----
    python find_shared_cookies.py --data cookies_data_processed
    python find_shared_cookies.py --data cookies_data_processed --min-sites 3
    python find_shared_cookies.py --data cookies_data_processed --match-mode value-entropy
    python find_shared_cookies.py --data cookies_data_processed --match-mode name-cluster
    python find_shared_cookies.py --data cookies_data_processed --third-party-only
    python find_shared_cookies.py --data cookies_data_processed --out shared_cookies.json
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from client.trackers.name_similarity import cluster_names

# total_bits cutoff for the value-entropy match mode. Mirrors the
# HIGH_ENTROPY_BITS constant in process_cookies.py; values below this are
# ignored in value-entropy mode to avoid grouping shared functional values
# (e.g. md5 of "true" appearing everywhere).
HIGH_ENTROPY_BITS = 36.0

# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_occurrences(data_dir: str) -> list[dict]:
    """Load a flat list of per-cookie occurrence records from processed JSON.

    Each record carries everything the grouping/reporting needs so the index
    can be built under any match mode without re-reading files.
    """
    json_files = sorted(Path(data_dir).glob("*.json"))
    if not json_files:
        print(f"[!] No .json files found in '{data_dir}'.", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Loading {len(json_files)} file(s) from '{data_dir}' ...")

    occurrences: list[dict] = []
    for path in json_files:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[!] Skipping {path.name}: {exc}", file=sys.stderr)
            continue

        site = data.get("target_url") or path.stem
        for cookie in data.get("cookies", []):
            name = cookie.get("name", "")
            md5 = cookie.get("md5_value", "")
            if not name or not md5:
                continue
            occurrences.append(
                {
                    "name": name,
                    "md5_value": md5,
                    "total_bits": cookie.get("total_bits", 0.0),
                    "site": site,
                    "source_file": path.name,
                    "domain": cookie.get("domain", ""),
                    "cookie_type": cookie.get("cookie_type", ""),
                    "party_type": cookie.get("party_type", "unknown"),
                    "is_tracker": cookie.get("is_tracker", False),
                }
            )

    if not occurrences:
        print(
            f"[!] No cookies with md5_value found in '{data_dir}'. "
            f"Did you run process_cookies.py first?",
            file=sys.stderr,
        )
        sys.exit(1)

    return occurrences


# ---------------------------------------------------------------------------
# Index construction (per match mode)
# ---------------------------------------------------------------------------


def build_index(
    occurrences: list[dict],
    match_mode: str,
) -> dict[tuple, list[dict]]:
    """Group occurrences into ``key -> [occurrence, ...]`` per match mode.

    Returns keys as tuples so the reporter can render them uniformly:
      name-md5      -> ("name", <name>, <md5>)
      value-entropy -> ("value", <md5>)
      name-cluster  -> ("cluster", <family>, <md5>)
    """
    index: dict[tuple, list[dict]] = defaultdict(list)

    if match_mode == "name-md5":
        for occ in occurrences:
            index[("name", occ["name"], occ["md5_value"])].append(occ)

    elif match_mode == "value-entropy":
        for occ in occurrences:
            if occ["total_bits"] >= HIGH_ENTROPY_BITS:
                index[("value", occ["md5_value"])].append(occ)

    elif match_mode == "name-cluster":
        families = cluster_names([occ["name"] for occ in occurrences])
        for occ in occurrences:
            family = families.get(occ["name"], occ["name"])
            index[("cluster", family, occ["md5_value"])].append(occ)

    else:  # pragma: no cover - guarded by argparse choices
        raise ValueError(f"Unknown match mode: {match_mode}")

    return index


# ---------------------------------------------------------------------------
# Filtering / shaping
# ---------------------------------------------------------------------------


def find_shared(
    index: dict[tuple, list[dict]],
    min_sites: int = 2,
    trackers_only: bool = False,
    third_party_only: bool = False,
) -> list[dict]:
    """Reduce the index to cross-site cookies and annotate party information."""
    results = []

    for key, occurrences in index.items():
        # Deduplicate by site so one site with multiple matching cookies
        # doesn't inflate the count; keep the first occurrence per site.
        sites_seen: dict[str, dict] = {}
        for occ in occurrences:
            sites_seen.setdefault(occ["site"], occ)

        if len(sites_seen) < min_sites:
            continue

        occs = list(sites_seen.values())
        party_types = [o["party_type"] for o in occs]
        has_third_party = any(p == "third_party" for p in party_types)

        if third_party_only and not has_third_party:
            continue
        if trackers_only and not any(bool(o.get("is_tracker")) for o in occs):
            continue

        distinct_first_parties = sum(1 for p in party_types if p == "first_party")
        any_tracker = any(bool(o.get("is_tracker")) for o in occs)
        domains = sorted({o["domain"] for o in occs})

        results.append(
            {
                "key_type": key[0],
                "label": _label_for_key(key),
                "md5_value": _md5_for_key(key),
                "site_count": len(sites_seen),
                "distinct_first_parties": distinct_first_parties,
                "has_third_party": has_third_party,
                "domains": domains,
                "any_tracker": any_tracker,
                "sites": [
                    {
                        "site": o["site"],
                        "source_file": o["source_file"],
                        "domain": o["domain"],
                        "cookie_type": o["cookie_type"],
                        "party_type": o["party_type"],
                        "name": o["name"],
                        "is_tracker": o["is_tracker"],
                    }
                    for o in sorted(occs, key=lambda x: x["site"])
                ],
            }
        )

    results.sort(key=lambda r: r["site_count"], reverse=True)
    return results


def _label_for_key(key: tuple) -> str:
    """Human-readable identifier for a group key."""
    if key[0] == "name":
        return key[1]
    if key[0] == "cluster":
        return f"{key[1]} (family)"
    return "<high-entropy value>"


def _md5_for_key(key: tuple) -> str:
    return key[-1]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_report(results: list[dict], min_sites: int, match_mode: str) -> None:
    if not results:
        print(f"\n[*] No cookies found on {min_sites}+ sites (mode={match_mode}).")
        return

    total_unique = len(results)
    tracker_count = sum(1 for r in results if r["any_tracker"])

    print(f"\n{'='*70}")
    print(f"  Shared cookies (mode={match_mode}, across >={min_sites} sites)")
    print(f"  Found {total_unique} group(s) - {tracker_count} involve a tracker cookie")
    print(f"{'='*70}\n")

    for i, r in enumerate(results, 1):
        tracker_label = " [known tracker]" if r["any_tracker"] else ""
        tp_label = " [3rd-party]" if r["has_third_party"] else ""
        print(f"  #{i:>4}  {r['label']!r}{tracker_label}{tp_label}")
        print(f"         md5         : {r['md5_value']}")
        print(f"         site count  : {r['site_count']}")
        print(f"         distinct 1p : {r['distinct_first_parties']}")
        print(f"         domains     : {', '.join(r['domains'])}")
        print(f"         sites       :")
        for s in r["sites"]:
            flags = []
            if s["is_tracker"]:
                flags.append("tracker")
            flags.append(s["party_type"])
            print(
                f"                     {s['site']}  ({s['cookie_type']}, {', '.join(flags)})"
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
        description="Find cookies shared across multiple crawled sites.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--data",
        default="../cookies_data_processed",
        metavar="DIR",
        help="Directory containing PROCESSED cookie JSON files (run process_cookies.py first).",
    )
    parser.add_argument(
        "--min-sites",
        type=int,
        default=2,
        metavar="N",
        help="Minimum number of distinct sites a group must appear on.",
    )
    parser.add_argument(
        "--match-mode",
        choices=["name-md5", "value-entropy", "name-cluster"],
        default="name-md5",
        help="How to group cookies into cross-site identities.",
    )
    parser.add_argument(
        "--trackers-only",
        action="store_true",
        default=False,
        help="Only report groups flagged as trackers on at least one site.",
    )
    parser.add_argument(
        "--third-party-only",
        action="store_true",
        default=False,
        help="Only report groups that appear in a third-party context on at least one site.",
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

    occurrences = load_occurrences(args.data)
    index = build_index(occurrences, args.match_mode)
    results = find_shared(
        index,
        min_sites=args.min_sites,
        trackers_only=args.trackers_only,
        third_party_only=args.third_party_only,
    )

    print_report(results, args.min_sites, args.match_mode)

    if args.out:
        write_json(results, args.out)


if __name__ == "__main__":
    main()
