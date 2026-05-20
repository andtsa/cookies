"""
scripts/get_cookie_reads.py
---------------------------
Crawl a list of websites and record every JS read of document.cookie.

Each site produces one JSON file under --output-dir:

    {
      "visited_domain": "example.com",
      "reads": [
        {
          "frame_url": "https://example.com/",
          "cookies":   "sessionid=abc; _ga=GA1.2.xxx",
          "stack":     "at Object.<anonymous> (analytics.js:1:42) | ...",
          "ts":        1716000000.123
        },
        ...
      ]
    }

Run find_read_trackers.py afterwards to compute which cookie names appear
across the most visited domains (the cross-domain signal for trackers).

Usage
-----
    # Single site
    python scripts/get_cookie_reads.py --url https://www.bbc.com

    # Batch from CSV (rank,domain per row)
    python scripts/get_cookie_reads.py --csv list_websites_1M.csv --limit 100

    # With more wait time and parallel workers
    python scripts/get_cookie_reads.py --csv sites.csv --wait 8000 --concurrency 4
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys

from playwright.async_api import async_playwright

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from client.trackers.reads import CookieReadInterceptor

# ---------------------------------------------------------------------------
# Core visit logic
# ---------------------------------------------------------------------------


async def visit_and_record(
    url: str,
    visited_domain: str,
    output_path: str,
    playwright_instance,
    wait_ms: int = 5000,
    timeout_ms: int = 15000,
    headless: bool = True,
) -> None:
    """
    Visit *url* with a fresh browser context, intercept all document.cookie
    getter calls, and write the session JSON to *output_path*.
    """
    interceptor = CookieReadInterceptor(visited_domain=visited_domain)

    browser = await playwright_instance.chromium.launch(headless=headless)
    context = await browser.new_context()
    page = await context.new_page()

    try:
        # Wire up interception BEFORE navigation so no reads are missed.
        await interceptor.attach(page)

        await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        await page.wait_for_timeout(wait_ms)

    except Exception as exc:
        print(f"  [!] {visited_domain}: {exc}", flush=True)

    finally:
        await browser.close()

    session_dict = interceptor.session.to_dict()
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(session_dict, fh, indent=2)

    n = len(session_dict["reads"])
    print(f"  [✓] {visited_domain}: {n} cookie-read event(s) recorded.", flush=True)


# ---------------------------------------------------------------------------
# Batch helpers
# ---------------------------------------------------------------------------


async def process_batch(
    domains: list[tuple[str, str]],  # [(visited_domain, url), ...]
    output_dir: str,
    wait_ms: int,
    timeout_ms: int,
    headless: bool,
    concurrency: int,
    overwrite: bool,
) -> None:
    semaphore = asyncio.Semaphore(concurrency)

    async with async_playwright() as pw:

        async def _visit(domain: str, url: str) -> None:
            output_path = os.path.join(output_dir, f"{domain}.json")
            if not overwrite and os.path.exists(output_path):
                print(f"  [–] {domain}: skipping (already exists).", flush=True)
                return
            async with semaphore:
                await visit_and_record(
                    url=url,
                    visited_domain=domain,
                    output_path=output_path,
                    wait_ms=wait_ms,
                    timeout_ms=timeout_ms,
                    headless=headless,
                    playwright_instance=pw,
                )

        tasks = [_visit(domain, url) for domain, url in domains]
        await asyncio.gather(*tasks)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_csv(path: str, limit: int | None) -> list[tuple[str, str]]:
    """Read (rank, domain) CSV → [(domain, https://domain), ...]."""
    entries = []
    with open(path, newline="", encoding="utf-8") as fh:
        for i, row in enumerate(csv.reader(fh)):
            if limit is not None and i >= limit:
                break
            if len(row) >= 2:
                domain = row[1].strip()
                entries.append((domain, f"https://{domain}"))
            elif len(row) == 1:
                domain = row[0].strip()
                entries.append((domain, f"https://{domain}"))
    return entries


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Crawl sites and record every JS document.cookie read.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="Visit a single URL (e.g. https://bbc.com).")
    source.add_argument("--csv", help="Path to CSV file (rank,domain per row).")

    p.add_argument(
        "--output-dir",
        default="../cookie_reads_data",
        help="Directory to write per-domain JSON files.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of sites to process (CSV mode).",
    )
    p.add_argument(
        "--wait",
        type=int,
        default=5000,
        help="Milliseconds to wait on each page after load.",
    )
    p.add_argument(
        "--timeout", type=int, default=15000, help="Navigation timeout in milliseconds."
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of parallel browser instances.",
    )
    p.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run browser headlessly.",
    )
    p.add_argument(
        "--overwrite",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Re-crawl sites that already have output.",
    )
    return p.parse_args()


async def main() -> None:
    args = parse_args()

    if args.url:
        from urllib.parse import urlparse

        domain = urlparse(args.url).hostname or args.url
        domain = domain.lstrip("www.")
        domains = [(domain, args.url)]
    else:
        print(f"Loading CSV: {args.csv}", flush=True)
        domains = _load_csv(args.csv, args.limit)
        print(f"  → {len(domains)} site(s) to crawl.", flush=True)

    await process_batch(
        domains=domains,
        output_dir=args.output_dir,
        wait_ms=args.wait,
        timeout_ms=args.timeout,
        headless=args.headless,
        concurrency=args.concurrency,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    asyncio.run(main())
