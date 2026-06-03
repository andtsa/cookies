"""
Memory profiling harness for the cookie crawler.

Instruments three layers:
  1. Process-level RSS (via psutil) sampled at key lifecycle events
  2. tracemalloc snapshots for per-allocation breakdowns
  3. Per-page counters (request_log length, JS events, HTML size)

Usage:
    python scripts/profile_memory.py --input list_websites_1M.csv --limit 20
    python scripts/profile_memory.py --urls example.com google.com --concurrency 3

All flags from get_cookies.py are supported via pass-through arguments.
Additional flags:
    --profile-top N     Top-N tracemalloc allocations to print (default: 20)
    --urls URL [URL ...] Visit specific URLs instead of reading from CSV
"""

import argparse
import asyncio
import os
import sys
import time
import tracemalloc
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import psutil

from classifier.sensitive_classifier import SensitiveClassifier
from client.api import Browser, ClientAPI
from client.config import BrowserConfig, CrawlConfig
from client.trackers import Detections, TrackerList
from client.trackers.matcher import EasyPrivacyMatcher

_proc = psutil.Process()
_page_stats: list[dict] = []
_rss_timeline: list[tuple[str, float]] = []  # (label, rss_mb)


def _rss_mb() -> float:
    return _proc.memory_info().rss / 1024 / 1024


def _snap(label: str) -> None:
    mb = _rss_mb()
    _rss_timeline.append((label, mb))
    print(f"  [MEM] {label:<45} RSS={mb:.1f} MB")


# ---------------------------------------------------------------------------
# Patched process_one — wraps the real one to record per-page memory delta
# ---------------------------------------------------------------------------

_orig_run_for_page = ClientAPI.run_for_page


async def _instrumented_run_for_page(url, output, cfg):
    from urllib.parse import urlparse

    netloc = urlparse(url).netloc or url
    before = _rss_mb()
    t0 = time.monotonic()

    await _orig_run_for_page(url, output, cfg)

    elapsed = time.monotonic() - t0
    after = _rss_mb()
    _page_stats.append(
        {
            "url": netloc,
            "rss_before_mb": round(before, 2),
            "rss_after_mb": round(after, 2),
            "rss_delta_mb": round(after - before, 2),
            "elapsed_s": round(elapsed, 2),
        }
    )
    print(
        f"  [PAGE] {netloc:<40} delta={after - before:+.1f} MB  elapsed={elapsed:.1f}s"
    )


ClientAPI.run_for_page = staticmethod(_instrumented_run_for_page)


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------


def _print_rss_timeline() -> None:
    print("\n" + "=" * 65)
    print("  RSS TIMELINE")
    print("=" * 65)
    baseline = _rss_timeline[0][1] if _rss_timeline else 0
    for label, mb in _rss_timeline:
        bar = "#" * max(0, int((mb - baseline) / 2))
        print(f"  {label:<45} {mb:6.1f} MB  +{mb - baseline:.1f}  {bar}")
    print()


def _print_page_stats() -> None:
    if not _page_stats:
        return
    print("=" * 65)
    print("  PER-PAGE MEMORY DELTAS")
    print("=" * 65)
    deltas = [s["rss_delta_mb"] for s in _page_stats]
    avg = sum(deltas) / len(deltas)
    mx = max(deltas)
    mn = min(deltas)
    print(f"  Pages visited : {len(_page_stats)}")
    print(f"  Delta avg     : {avg:+.1f} MB")
    print(f"  Delta max     : {mx:+.1f} MB")
    print(f"  Delta min     : {mn:+.1f} MB")
    print()
    print(f"  {'URL':<40} {'before':>8} {'after':>8} {'delta':>8} {'time':>7}")
    print(f"  {'-'*40} {'-'*8} {'-'*8} {'-'*8} {'-'*7}")
    for s in sorted(_page_stats, key=lambda x: x["rss_delta_mb"], reverse=True):
        print(
            f"  {s['url']:<40} {s['rss_before_mb']:>8.1f} {s['rss_after_mb']:>8.1f}"
            f" {s['rss_delta_mb']:>+8.1f} {s['elapsed_s']:>6.1f}s"
        )
    print()


def _print_tracemalloc(top_n: int) -> None:
    snapshot = tracemalloc.take_snapshot()
    stats = snapshot.statistics("lineno")
    print("=" * 65)
    print(f"  TRACEMALLOC TOP {top_n} ALLOCATIONS (by size)")
    print("=" * 65)
    total = sum(s.size for s in stats)
    print(f"  Total tracked : {total / 1024 / 1024:.2f} MB\n")
    for stat in stats[:top_n]:
        frame = stat.traceback[0]
        # shorten path to relative
        path = frame.filename.replace(
            os.path.join(os.path.dirname(__file__), "..") + "/", ""
        )
        print(f"  {stat.size / 1024:>8.1f} KB   {path}:{frame.lineno}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Memory profiling harness for the cookie crawler.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input", "-i", default=None, help="CSV input file")
    parser.add_argument(
        "--urls",
        nargs="+",
        metavar="URL",
        help="Explicit URLs to visit (overrides --input)",
    )
    parser.add_argument("--output-dir", default="profile_output")
    parser.add_argument(
        "--browsers",
        nargs="+",
        choices=[b.value for b in Browser],
        default=[Browser.CHROMIUM.value],
    )
    parser.add_argument("--timeout-ms", type=int, default=10000)
    parser.add_argument("--wait-time-ms", type=int, default=3000)
    parser.add_argument("--headless", type=bool, default=True)
    parser.add_argument("--limit", "-l", type=int, default=None)
    parser.add_argument("--concurrency", "-c", type=int, default=1)
    parser.add_argument("--overwrite", "-O", action="store_true", default=True)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--no-tracker-lists", action="store_true", default=False)
    parser.add_argument("--tracker-cache-dir", default=".tracker_cache")
    parser.add_argument(
        "--cookie-reads", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--classifier", action="store_true", default=False)
    parser.add_argument("--profile-top", type=int, default=20, metavar="N")

    args = parser.parse_args()

    if args.urls is None and args.input is None:
        parser.error("Provide --input CSV or --urls URL [URL ...]")

    browsers = [Browser(b) for b in args.browsers]
    concurrency = max(1, args.concurrency)

    # --- start tracemalloc early so startup allocations are captured ----------
    tracemalloc.start()
    _snap("startup (before tracker list load)")

    tracker_list = None
    matcher = None
    classifier = None

    if not args.no_tracker_lists:
        tracker_list = TrackerList()
        tracker_list.load(
            trackers={Detections.OpenCookieDB, Detections.EasyPrivacy},
            cache_dir=args.tracker_cache_dir,
        )
        _snap("after tracker list load")

    if args.classifier:
        classifier = SensitiveClassifier()
        _snap("after classifier load")

    crawl_cfg = CrawlConfig(
        concurrency=concurrency,
        limit=args.limit,
        overwrite=args.overwrite,
    )

    if tracker_list is not None:
        matcher = EasyPrivacyMatcher(tracker_list._easyprivacy)

    async def run_all():
        if args.urls:
            batches = [args.urls]
        else:
            import pandas as pd

            batches = list(
                pd.read_csv(
                    args.input,
                    header=0,
                    names=["rank", "url"],
                    chunksize=args.batch_size,
                    nrows=crawl_cfg.limit,
                )
            )

        batch_num = 0
        for batch in batches:
            batch_num += 1
            urls = list(batch) if isinstance(batch, list) else batch["url"].tolist()
            _snap(f"batch {batch_num} start ({len(urls)} URLs)")
            for browser in browsers:
                browser_cfg = BrowserConfig(
                    headless=args.headless,
                    timeout_ms=args.timeout_ms,
                    wait_time_ms=args.wait_time_ms,
                    tracker_list=tracker_list,
                    matcher=matcher,
                    intercept_cookie_reads=args.cookie_reads,
                    browser_type=browser,
                    classifier=classifier,
                )
                await ClientAPI.process_batch(
                    websites=urls,
                    output_dir=f"{args.output_dir}/{browser.value}",
                    browser_cfg=browser_cfg,
                    crawl_cfg=crawl_cfg,
                )
            _snap(f"batch {batch_num} end")

        _snap("all batches done")

    asyncio.run(run_all())

    # --- final reports -------------------------------------------------------
    _print_rss_timeline()
    _print_page_stats()
    _print_tracemalloc(args.profile_top)

    tracemalloc.stop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted — printing partial results...\n")
        _print_rss_timeline()
        _print_page_stats()
        tracemalloc.stop()
