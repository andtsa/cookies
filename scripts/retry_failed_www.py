"""
scripts/retry_failed_www.py
---------------------------
Re-crawl the sites recorded in each ``{data}/{country}/{browser}/failed_sites.csv``
with ``www.`` prepended to the host, now that the main crawl has already run.

Why this exists
===============
The crawler navigates to the exact host from the input list, only prepending a
scheme (``client/api.py``). It has **no www fallback**: a site whose apex does
not resolve while ``www.<host>`` does is recorded as a failure (mostly
``ERR_NAME_NOT_RESOLVED`` on chromium) and contributes zero cookies. GUI
browsers paper over this in the omnibox by retrying ``www.`` on a DNS failure;
``page.goto`` does not. This tool replays those failures once with ``www.``
prepended, reusing the *same* client pipeline (tracker annotation, cookie-read
interception, output format) so a recovered site is indistinguishable from one
collected in the original crawl.

Safety / idempotency
====================
- Output lands at the normal sharded path keyed on the *www* netloc, so it never
  collides with the original (apex) output. ``registered_domain`` strips the
  leading ``www`` (tldextract), so the analysis package folds it back to the same
  site automatically.
- A recovered site is skipped on a second run (``overwrite=False``), so the tool
  is safe to re-run.
- Anything that *still* fails is written to ``failed_sites_www_retry.csv`` next
  to the original file; the original ``failed_sites.csv`` is left untouched.

Category note
=============
``failed_sites.csv`` does not record the crawl ``--category`` (it is a run-level
flag, not per-row). The recovered sites here are top-ranked popular domains, so
``--category`` defaults to ``popular``; pass ``--category medical`` if you are
replaying a health-list crawl.

Usage
=====
    python scripts/retry_failed_www.py                      # everything, all browsers
    python scripts/retry_failed_www.py --only-dns           # only DNS-resolution failures
    python scripts/retry_failed_www.py --browsers chromium  # one browser
    python scripts/retry_failed_www.py --dry-run            # list targets, no network
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import glob
import os
import sys
from urllib.parse import urlparse, urlunparse

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from client.api import ClientAPI  # noqa: E402
from client.config import Browser, BrowserConfig, CrawlConfig, Site  # noqa: E402
from client.trackers import Detections, TrackerList  # noqa: E402
from crawler.engine import kill_orphaned_browsers  # noqa: E402

# DNS-resolution error reasons across engines — the failures www actually fixes.
# (chromium: ERR_NAME_NOT_RESOLVED; firefox/webkit: NS_ERROR_UNKNOWN_HOST)
_DNS_REASONS = {"ERR_NAME_NOT_RESOLVED", "NS_ERROR_UNKNOWN_HOST"}

_FAILED_NAME = "failed_sites.csv"
_RETRY_FAILED_NAME = "failed_sites_www_retry.csv"


def _prepend_www(url: str) -> str | None:
    """Return ``url`` with ``www.`` prepended to its host, or None if N/A.

    None means "don't retry this one": no host, or the host is already ``www.``
    (replaying the identical URL that already failed would be pointless).
    """
    if "://" not in url:
        url = "https://" + url
    parts = urlparse(url)
    host = parts.hostname or ""
    if not host or host.startswith("www."):
        return None
    netloc = "www." + host
    if parts.port:
        netloc += f":{parts.port}"
    return urlunparse(
        (
            parts.scheme,
            netloc,
            parts.path or "",
            parts.params,
            parts.query,
            parts.fragment,
        )
    )


def _read_targets(path: str, only_dns: bool) -> list[tuple[int, str]]:
    """Unique ``(rank, www_url)`` retry targets parsed from a failed_sites.csv.

    The file is headerless ``rank,url,reason,msg`` (written by
    ``client.api._write_failed_site``). Duplicate URLs (the file is append-only)
    are collapsed.
    """
    seen: set[str] = set()
    targets: list[tuple[int, str]] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 2:
                continue
            rank_s, url = row[0].strip(), row[1].strip()
            reason = row[2].strip() if len(row) > 2 else ""
            if only_dns and reason not in _DNS_REASONS:
                continue
            www = _prepend_www(url)
            if not www or www in seen:
                continue
            seen.add(www)
            try:
                rank = int(rank_s)
            except ValueError:
                rank = 0
            targets.append((rank, www))
    return targets


async def _crawl_group(
    targets: list[tuple[int, str]],
    *,
    country: str,
    browser: str,
    data_root: str,
    category: str,
    tracker_list: TrackerList | None,
    concurrency: int,
    timeout_ms: int,
    wait_ms: int,
    cookie_reads: bool,
) -> dict[str, int]:
    """Re-crawl one (country, browser) group; return an ok/fail/skip tally."""
    browser_cfg = BrowserConfig(
        headless=True,
        timeout_ms=timeout_ms,
        wait_time_ms=wait_ms,
        tracker_list=tracker_list,
        intercept_cookie_reads=cookie_reads,
        browser_type=Browser(browser),
    )
    crawl_cfg = CrawlConfig(
        concurrency=concurrency,
        overwrite=False,  # keep an already-recovered www site; this is re-runnable
        failed_sites_path=_RETRY_FAILED_NAME,  # don't touch the original failed file
        output_dir=f"{data_root}/{country}",
        country=country,
    )

    sem = asyncio.Semaphore(concurrency)
    tally = {"ok": 0, "fail": 0, "skip": 0}

    async def _one(rank: int, url: str) -> None:
        async with sem:
            result = await ClientAPI.process_url(
                Site(url=url, rank=rank, category=category), browser_cfg, crawl_cfg
            )
        tally["ok" if result is True else "skip" if result is None else "fail"] += 1

    await asyncio.gather(*[_one(r, u) for r, u in targets], return_exceptions=True)
    return tally


def _discover(data_root: str, country: str | None, browsers: list[str] | None):
    """Yield ``(path, country, browser, targets-less)`` for each failed file."""
    pattern = os.path.join(data_root, "*", "*", _FAILED_NAME)
    for path in sorted(glob.glob(pattern)):
        rel = os.path.relpath(path, data_root).split(os.sep)
        if len(rel) != 3:
            continue
        c, b, _ = rel
        if country and c != country:
            continue
        if browsers and b not in browsers:
            continue
        yield path, c, b


async def _run_all(files, *, data_root, category, tracker_list, args) -> None:
    grand = {"ok": 0, "fail": 0, "skip": 0}
    # Sequential across (country, browser) groups so we never run two browser
    # engines at once; sites within a group go concurrently.
    for path, country, browser in files:
        targets = _read_targets(path, args.only_dns)
        if not targets:
            print(f"[{country}/{browser}] no retry targets")
            continue
        print(
            f"\n[{country}/{browser}] retrying {len(targets)} site(s) with www. prepended"
        )
        tally = await _crawl_group(
            targets,
            country=country,
            browser=browser,
            data_root=data_root,
            category=category,
            tracker_list=tracker_list,
            concurrency=args.concurrency,
            timeout_ms=args.timeout_ms,
            wait_ms=args.wait_time_ms,
            cookie_reads=args.cookie_reads,
        )
        print(
            f"[{country}/{browser}] recovered={tally['ok']} "
            f"still-failed={tally['fail']} skipped={tally['skip']} "
            f"(still-failed logged to {os.path.dirname(path)}/{_RETRY_FAILED_NAME})"
        )
        for k in grand:
            grand[k] += tally[k]

    print(
        f"\n{'='*60}\n  Total: recovered={grand['ok']} "
        f"still-failed={grand['fail']} skipped={grand['skip']}\n{'='*60}"
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    p.add_argument(
        "--data",
        default="cookies_data",
        help="crawl output root (default: cookies_data)",
    )
    p.add_argument(
        "--country", default=None, help="limit to one country (default: all found)"
    )
    p.add_argument(
        "--browsers",
        nargs="+",
        default=None,
        help="limit to these browsers (default: all found)",
    )
    p.add_argument(
        "--category",
        default="popular",
        help="category to stamp on recovered sites (default: popular)",
    )
    p.add_argument(
        "--only-dns",
        action="store_true",
        help="retry only DNS-resolution failures (the ones www actually fixes); default retries every failed row",
    )
    p.add_argument(
        "--concurrency",
        "-c",
        type=int,
        default=4,
        help="concurrent sites per browser (default: 4)",
    )
    p.add_argument("--timeout-ms", type=int, default=10000)
    p.add_argument("--wait-time-ms", type=int, default=5000)
    p.add_argument(
        "--tracker-lists", action=argparse.BooleanOptionalAction, default=True
    )
    p.add_argument("--tracker-cache-dir", default=".tracker_cache")
    p.add_argument(
        "--cookie-reads", action=argparse.BooleanOptionalAction, default=True
    )
    p.add_argument(
        "--dry-run", action="store_true", help="list targets and exit without crawling"
    )
    args = p.parse_args()

    files = list(_discover(args.data, args.country, args.browsers))
    if not files:
        print(
            f"No {_FAILED_NAME} found under {args.data!r} (country={args.country}, browsers={args.browsers})."
        )
        return

    if args.dry_run:
        total = 0
        for path, country, browser in files:
            targets = _read_targets(path, args.only_dns)
            total += len(targets)
            print(f"[{country}/{browser}] {len(targets)} target(s) from {path}")
            for rank, url in targets[:10]:
                print(f"    {rank:>7}  {url}")
            if len(targets) > 10:
                print(f"    ... and {len(targets) - 10} more")
        print(
            f"\nTotal retry targets: {total}  (category={args.category}, only_dns={args.only_dns})"
        )
        return

    tracker_list = None
    if args.tracker_lists:
        tracker_list = TrackerList()
        tracker_list.load(
            trackers={Detections.OpenCookieDB, Detections.EasyPrivacy},
            cache_dir=args.tracker_cache_dir,
        )

    kill_orphaned_browsers()
    try:
        asyncio.run(
            _run_all(
                files,
                data_root=args.data,
                category=args.category,
                tracker_list=tracker_list,
                args=args,
            )
        )
    except KeyboardInterrupt:
        print("\nInterrupted by user")


if __name__ == "__main__":
    main()
