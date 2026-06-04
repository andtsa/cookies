import argparse
import asyncio
import os
import sys

import psutil

from client.api import Browser
from client.config import BrowserConfig, CrawlConfig
from client.trackers import Detections, TrackerList
from client.trackers.matcher import EasyPrivacyMatcher
from .engine import CrawlEngine


def main():
    parser = argparse.ArgumentParser(
        description="Collect cookies from a list of websites provided via CSV."
    )
    parser.add_argument(
        "--input",
        "-i",
        default="list_websites_1M.csv",
        help="Path to the CSV file containing URLs to process.",
    )
    parser.add_argument(
        "--output-dir",
        default="cookies_data",
        help="Directory to write output JSON files to (default: cookies_data).",
    )
    parser.add_argument(
        "--browsers",
        nargs="+",
        choices=[b.value for b in Browser],
        default=[Browser.CHROMIUM.value],
        metavar="BROWSER",
        help=(
            "One or more browsers to use. Each site is visited once per browser. "
            f"Choices: {', '.join(b.value for b in Browser)}. "
            "Default: chromium. Example: --browsers chromium webkit firefox"
        ),
    )
    parser.add_argument(
        "--country",
        default="Netherlands",
        help="From which country is the crawl running (default: Netherlands).",
    )
    parser.add_argument(
        "--category",
        default="popular",
        help="Category of the site (default: popular).",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=10000,
        help="Page load timeout in milliseconds (default: 10000).",
    )
    parser.add_argument(
        "--wait-time-ms",
        type=int,
        default=5000,
        help="Time to wait on each page after load in milliseconds (default: 5000).",
    )
    parser.add_argument(
        "--headless",
        type=bool,
        default=True,
        help="Whether to run the browser in headless mode (default: True).",
    )
    parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=None,
        help="Maximum number of URLs to process.",
    )
    parser.add_argument(
        "--concurrency",
        "-c",
        type=int,
        default=1,
        help="Number of websites to process simultaneously (default: 1).",
    )
    parser.add_argument(
        "--force-concurrency",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Force crawler to use specified concurrency despite cpu core check.",
    )
    parser.add_argument(
        "--overwrite",
        "-O",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Overwrite existing output files (default: skip already-collected sites).",
    )
    parser.add_argument(
        "--failed-sites",
        default="failed_sites.csv",
        help="Append failed domain names to this file (default: disabled).",
    )
    parser.add_argument(
        "--sleep-between-ms",
        type=int,
        default=0,
        metavar="MS",
        help="Milliseconds to sleep between page visits (default: 0).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Number of sites to process per browser per round (default: 20)",
    )
    parser.add_argument(
        "--skip-first",
        type=int,
        default=0,
        help="How many rows to skip from the start of the input csv",
    )

    tracker_group = parser.add_argument_group(
        "tracker annotation", "Annotate each cookie with is_tracker using filter lists."
    )
    tracker_group.add_argument(
        "--tracker-lists",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable tracker annotation. Downloads default lists to annotate each cookie with is_tracker.",
    )
    tracker_group.add_argument(
        "--tracker-cache-dir",
        default=".tracker_cache",
        metavar="DIR",
        help="Directory to cache downloaded filter lists (default: .tracker_cache)",
    )
    parser.add_argument(
        "--cookie-reads",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Intercept and record all JS document.cookie reads per page.",
    )
    parser.add_argument(
        "--classifier",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use a classifier to determine whether a website is sensitive or not",
    )

    args = parser.parse_args()
    browsers = [Browser(b) for b in args.browsers]

    concurrency_explicit = any(a in sys.argv for a in ("--concurrency", "-c"))
    if not concurrency_explicit and not args.force_concurrency:
        cores = os.cpu_count() or 1
        cpu_based = max(1, cores - 1)
        mem = psutil.virtual_memory()
        mb_per_slot = 400 if len(args.browsers) == 1 else 500
        mem_based = max(1, int(mem.available / (mb_per_slot * 1024 * 1024)))
        suggested = min(cpu_based, mem_based)
        print(
            f"[Crawler] Auto-tune: cpu_based={cpu_based}, mem_based={mem_based} "
            f"({mem.available // 1024 // 1024} MB avail / {mb_per_slot} MB per slot) "
            f"-> concurrency={suggested}"
        )
        args.concurrency = suggested

    concurrency = args.concurrency or 1
    cores = os.cpu_count()
    if cores and concurrency > cores and not args.force_concurrency:
        print(
            f"[Crawler] Note: concurrency ({concurrency}) > cores ({cores}). "
            f"This is fine for I/O-bound crawling. Pass --force-concurrency to silence."
        )

    tracker_list = None
    matcher = None
    classifier = None
    if args.tracker_lists:
        tracker_list = TrackerList()
        tracker_list.load(
            trackers={Detections.OpenCookieDB, Detections.EasyPrivacy},
            cache_dir=args.tracker_cache_dir,
        )
        matcher = EasyPrivacyMatcher(tracker_list._easyprivacy)
    if args.classifier:
        from classifier.sensitive_classifier import SensitiveClassifier

        classifier = SensitiveClassifier()

    crawl_cfg = CrawlConfig(
        concurrency=concurrency,
        limit=args.limit,
        overwrite=args.overwrite,
        failed_sites_path=args.failed_sites,
        sleep_between_ms=args.sleep_between_ms,
        output_dir=f"{args.output_dir}/{args.country}",
        country=args.country,
    )

    progress_file = os.path.join(crawl_cfg.output_dir, "progress.txt")
    if args.skip_first:
        start_index = args.skip_first
    elif os.path.exists(progress_file):
        with open(progress_file) as pf:
            start_index = int(pf.read().strip())
        print(
            f"[Crawler] Auto-resuming from site {start_index} (found {progress_file})"
        )
    else:
        start_index = 0

    browser_cfgs = [
        BrowserConfig(
            headless=args.headless,
            timeout_ms=args.timeout_ms,
            wait_time_ms=args.wait_time_ms,
            tracker_list=tracker_list,
            matcher=matcher,
            intercept_cookie_reads=args.cookie_reads,
            browser_type=browser,
            classifier=classifier,
        )
        for browser in browsers
    ]

    total_sites = args.limit or (
        1000000 if "list_websites_1M.csv" in args.input else None
    )

    engine = CrawlEngine(
        crawl_cfg=crawl_cfg,
        browser_cfgs=browser_cfgs,
        batch_size=args.batch_size,
        start_index=start_index,
        total_sites=total_sites,
        progress_file=progress_file,
        input_path=args.input,
        category=args.category,
    )

    try:
        asyncio.run(engine.run())
    except KeyboardInterrupt:
        print("Interrupted by user")
    except asyncio.CancelledError:
        pass
