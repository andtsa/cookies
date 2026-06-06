"""
scripts/find_read_trackers.py
-----------------------------
Analyse the JSON files produced by get_cookie_reads.py and identify cookies
that were *read* by JavaScript on multiple distinct visited domains.

The hypothesis: if a cookie with the same name is read on N unrelated
first-party domains, it is almost certainly a cross-site tracker.

Output columns
--------------
cookie_name   – the cookie's JS key
domain_count  – number of distinct visited domains where it was read
domains       – comma-separated list of those domains (truncated if long)

Usage
-----
    # Basic: flag anything read on ≥ 2 domains
    python scripts/find_read_trackers.py cookie_reads_data/

    # Stricter threshold
    python scripts/find_read_trackers.py cookie_reads_data/ --min-domains 5

    # Save to JSON for downstream use
    python scripts/find_read_trackers.py cookie_reads_data/ --out results.json

    # Show per-domain breakdown for a specific cookie
    python scripts/find_read_trackers.py cookie_reads_data/ --inspect _ga
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
import tldextract
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from client.trackers.reads import build_cookie_domain_index, find_cross_domain_cookies


URL_RE = re.compile(r"https?://[^\s)]+")
# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def load_sessions(data_dir: str) -> list[dict]:
    """Load InterceptorSession dicts from data_dir.

    Supports two layouts:
    - Old: standalone session JSON files (``{visited_domain, reads}`` at top level)
    - New: session embedded as ``data["cookie_reads"]`` inside the site JSON
      (which also contains ``cookies``, ``site_metadata``, etc.)

    Files without cookie_read data are silently skipped.
    """
    sessions = []
    # Search recursively to handle both flat and browser-subdirectory layouts.
    pattern = os.path.join(data_dir, "**", "*.json")
    paths = sorted(glob.glob(pattern, recursive=True))
    if not paths:
        print(f"No JSON files found in: {data_dir}", file=sys.stderr)
        sys.exit(1)
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            print(f"  [!] Skipping {path}: {exc}", file=sys.stderr)
            continue
        # New schema: cookie_reads is embedded inside the site JSON.
        # Old schema: the file IS the session dict (has visited_domain at top level).
        session = data.get("cookie_reads") if "cookie_reads" in data else data
        if session and session.get("reads"):
            sessions.append(session)
    return sessions


# ---------------------------------------------------------------------------
# Report printers
# ---------------------------------------------------------------------------


def print_table(results: list[dict], max_domains_shown: int = 60) -> None:
    if not results:
        print("No cross-domain cookies found.")
        return

    name_w = max(len(r["cookie_name"]) for r in results)
    name_w = max(name_w, 11)  # min width for header

    header = f"{'cookie_name':<{name_w}}  {'domains':>7}  top visited domains"
    print(header)
    print("-" * len(header))

    for r in results:
        domains_preview = ", ".join(r["domains"][:max_domains_shown])
        if r["domain_count"] > max_domains_shown:
            domains_preview += f", … (+{r['domain_count'] - max_domains_shown} more)"
        print(
            f"{r['cookie_name']:<{name_w}}  {r['domain_count']:>7}  {domains_preview}"
        )


def print_inspect(index: dict[str, set[str]], cookie_name: str) -> None:
    domains = index.get(cookie_name)
    if domains is None:
        print(f"Cookie '{cookie_name}' not found in any session.")
        return
    print(f"Cookie '{cookie_name}' was JS-read on {len(domains)} domain(s):")
    for d in sorted(domains):
        print(f"  • {d}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Find cookies JS-read across multiple visited domains.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("data_dir", help="Directory of JSON files from get_cookie_reads.py.")
    p.add_argument(
        "--min-domains",
        type=int,
        default=2,
        help="Minimum distinct visited domains to flag a cookie.",
    )
    p.add_argument("--out", default=None, help="Optional path to write JSON results.")
    p.add_argument(
        "--inspect",
        default=None,
        metavar="COOKIE_NAME",
        help="Show the full domain list for one specific cookie name.",
    )
    return p.parse_args()


def build_cookie_reader_details(
    sessions: list[dict],
) -> dict[str, list[dict]]:

    result = defaultdict(list)

    for session in sessions:

        visited_domain = session.get("visited_domain", "")

        for read in session.get("reads", []):

            stack = read.get("stack", "")

            reader_domain, reader_script = extract_primary_reader(stack)

            raw = read.get("cookies", "")

            for part in raw.split(";"):

                part = part.strip()

                if not part:
                    continue

                cookie_name = part.split("=", 1)[0].strip()

                if not cookie_name:
                    continue

                result[cookie_name].append(
                    {
                        "visited_domain": visited_domain,
                        "reader_domain": reader_domain,
                        "reader_script": reader_script,
                    }
                )

    return dict(result)



def extract_primary_reader(stack: str) -> tuple[str | None, str | None]:
    """
    Extract the first script URL found in the stack trace and
    return (reader_domain, reader_script_url).
    """

    urls = URL_RE.findall(stack)

    if not urls:
        return None, None

    script_url = urls[0]

    ext = tldextract.extract(script_url)

    reader_domain = ".".join(
        p for p in [ext.domain, ext.suffix] if p
    )

    return reader_domain, script_url

def filter_third_party_readers(
    details: dict[str, list[dict]]
) -> dict[str, list[dict]]:

    filtered = {}

    for cookie_name, entries in details.items():

        keep = []
        seen = set()

        for entry in entries:

            visited = entry.get("visited_domain")
            reader = entry.get("reader_domain")
            script = entry.get("reader_script")

            # Skip unknown readers
            if not reader:
                continue

            # Skip first-party readers
            if reader == visited:
                continue

            key = (
                visited,
                reader,
                script,
            )

            # Deduplicate identical reads
            if key in seen:
                continue

            seen.add(key)
            keep.append(entry)

        if keep:
            filtered[cookie_name] = keep

    return filtered

def main() -> None:
    args = parse_args()

    print(f"Loading sessions from: {args.data_dir}")
    sessions = load_sessions(args.data_dir)
    print(f"  -> {len(sessions)} session file(s) loaded.\n")

    index = build_cookie_domain_index(sessions)
    print(f"Unique cookie names seen: {len(index)}\n")

    if args.inspect:
        print_inspect(index, args.inspect)
        return

    results = find_cross_domain_cookies(index, min_domains=args.min_domains)
    print(f"Cookies read on ≥ {args.min_domains} distinct domain(s): {len(results)}\n")
    print_table(results)

    details = build_cookie_reader_details(sessions)
    filtered_details = filter_third_party_readers(details)

    base = args.out.removesuffix(".json")

    results_path = f"{base}.json"
    details_path = f"{base}_details.json"
    filtered_path = f"{base}_filtered.json"

    with open(results_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)

    with open(details_path, "w", encoding="utf-8") as fh:
        json.dump(details, fh, indent=2)

    with open(filtered_path, "w", encoding="utf-8") as fh:
        json.dump(filtered_details, fh, indent=2)

    print(f"Results written to: {results_path}")
    print(f"Details written to: {details_path}")
    print(f"Third-party details written to: {filtered_path}")


if __name__ == "__main__":
    main()
