import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from client.client_utils import Browser, ClientUtils
from client.trackers import DEFAULT_LIST_URLS, TrackerList


def main():
    parser = argparse.ArgumentParser(
        description="Collect cookies from a list of websites provided via CSV."
    )
    parser.add_argument(
        "source_file_path", help="Path to the CSV file containing URLs to process."
    )
    parser.add_argument(
        "--output-dir",
        default="cookies_data",
        help="Directory to write output JSON files to (default: cookies_data).",
    )
    parser.add_argument(
        "--browser",
        choices=[b.value for b in Browser],
        default=Browser.CHROMIUM.value,
        help="Browser to use for visiting pages (default: chromium).",
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
        "--headless", action="store_true", help="Run browser in headless mode."
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Maximum number of URLs to process."
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of websites to process simultaneously (default: 1).",
    )

    tracker_group = parser.add_argument_group(
        "tracker annotation", "Annotate each cookie with is_tracker using filter lists."
    )
    tracker_group.add_argument(
        "--tracker-lists",
        action="store_true",
        default=False,
        help="Enable tracker annotation. Downloads default lists to annotate each cookie with is_tracker.",
    )
    tracker_group.add_argument(
        "--tracker-cache-dir",
        default=".tracker_cache",
        metavar="DIR",
        help="Directory to cache downloaded filter lists (default: .tracker_cache)",
    )

    args = parser.parse_args()
    browser = Browser(args.browser)

    tracker_list = None
    if args.tracker_lists:
        tracker_list = TrackerList()
        tracker_list.load(urls=DEFAULT_LIST_URLS, cache_dir=args.tracker_cache_dir)

    asyncio.run(
        ClientUtils.process_batch_from_csv(
            source_file_path=args.source_file_path,
            output_dir=args.output_dir,
            browser=browser,
            timeout_ms=args.timeout_ms,
            headless=args.headless,
            limit=args.limit,
            wait_time_ms=args.wait_time_ms,
            concurrency=args.concurrency,
            tracker_list=tracker_list,
        )
    )


if __name__ == "__main__":
    main()
