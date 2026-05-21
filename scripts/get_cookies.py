import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from classifier.sensitive_classifier import SensitiveClassifier
from client.api import Browser, ClientAPI
from client.config import BrowserConfig, CrawlConfig
from client.trackers import Detections, TrackerList
from client.trackers.matcher import EasyPrivacyMatcher


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
        "--overwrite",
        "-O",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Overwrite existing output files (default: skip already-collected sites).",
    )
    parser.add_argument(
        "--failed-sites",
        metavar="FILE",
        default=None,
        help="Append failed domain names to this file (default: disabled).",
    )
    parser.add_argument(
        "--sleep-between-ms",
        type=int,
        default=0,
        metavar="MS",
        help="Milliseconds to sleep between page visits (default: 0).",
    )

    tracker_group = parser.add_argument_group(
        "tracker annotation", "Annotate each cookie with is_tracker using filter lists."
    )
    tracker_group.add_argument(
        "--tracker-lists",
        action="store_true",
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
        action="store_true",
        default=True,
        help="Intercept and record all JS document.cookie reads per page.",
    )
    parser.add_argument(
        "--classifier",
        action="store_true",
        default=True,
        help="Use a classifier to determine whether a website is sensitive or not",
    )

    args = parser.parse_args()
    browsers = [Browser(b) for b in args.browsers]

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
        classifier = SensitiveClassifier()

    crawl_cfg = CrawlConfig(
        concurrency=args.concurrency,
        limit=args.limit,
        overwrite=args.overwrite,
        failed_sites_path=args.failed_sites,
        sleep_between_ms=args.sleep_between_ms,
    )

    async def run_all():
        for browser in browsers:
            if len(browsers) > 1:
                print(f"\n{'='*60}")
                print(f"  Browser: {browser.value}  ({browsers.index(browser)+1}/{len(browsers)})")
                print(f"{'='*60}")
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
            await ClientAPI.process_batch_from_csv(
                source_file_path=args.input,
                output_dir=args.output_dir,
                browser_cfg=browser_cfg,
                crawl_cfg=crawl_cfg,
            )

    asyncio.run(run_all())


if __name__ == "__main__":
    main()
