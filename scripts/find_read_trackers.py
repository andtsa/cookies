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
    python scripts/find_read_trackers.py --data cookie_reads_data/

    # Stricter threshold
    python scripts/find_read_trackers.py --data cookie_reads_data/ --min-domains 5

    # Save to JSON for downstream use
    python scripts/find_read_trackers.py --data cookie_reads_data/ --out results.json

    # Show per-domain breakdown for a specific cookie
    python scripts/find_read_trackers.py --data cookie_reads_data/ --inspect _ga
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from client.trackers.js import build_cookie_domain_index, find_cross_domain_cookies

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
        # New schema: js_activity embedded inside site JSON (no visited_domain inside).
        # Previous schema: cookie_reads embedded with visited_domain inside.
        # Legacy schema: the file IS the session dict (has visited_domain at top level).
        if "js_activity" in data:
            session = dict(data["js_activity"])
            session["visited_domain"] = urlparse(data.get("target_url", "")).netloc
        elif "cookie_reads" in data:
            session = data["cookie_reads"]
        else:
            session = data
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
    p.add_argument(
        "--data",
        default="../cookies_data",
        metavar="DIR",
        help="Directory containing the raw cookie JSON files.",
    )
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

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2)
        print(f"\nResults written to: {args.out}")


if __name__ == "__main__":
    main()
