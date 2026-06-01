import argparse
import asyncio
import os
import signal
import sys
import pandas as pd
import time
from datetime import datetime

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

    concurrency = args.concurrency or 1
    cores = os.cpu_count()
    if cores and concurrency > cores:
        print(
            f"Concurrency ({concurrency}) exceeds available cores ({cores}), setting to {cores - 1} to ensure stability"
        )
        # if laptop is left overnight and it enters power saving mode,
        # the switching between the crawling task and the OS might take so long
        # that the laptop's hardware watchdog reboots it (happened to me)
        concurrency = cores - 1

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
        concurrency=concurrency,
        limit=args.limit,
        overwrite=args.overwrite,
        failed_sites_path=args.failed_sites,
        sleep_between_ms=args.sleep_between_ms,
    )

    batch_size = args.batch_size or 20

    # auto-resume: if --skip-first was not explicitly set and a progress file
    # exists in the output directory, pick up from where the last run stopped
    progress_file = os.path.join(args.output_dir, "progress.txt")
    if args.skip_first:
        start_index = args.skip_first
    elif os.path.exists(progress_file):
        with open(progress_file) as _pf:
            start_index = int(_pf.read().strip())
        print(
            f"[Crawler] Auto-resuming from site {start_index} (found {progress_file})"
        )
    else:
        start_index = 0

    async def run_all():
        loop = asyncio.get_running_loop()
        main_task = asyncio.current_task()

        # Treat SIGTERM the same as Ctrl-C, cancel the main task so asyncio
        # can clean up running tasks before the process exits
        def _on_sigterm():
            print("\n[Crawler] Received SIGTERM, cancelling crawl...")
            if main_task:
                main_task.cancel()

        loop.add_signal_handler(signal.SIGTERM, _on_sigterm)

        processed_sites = start_index
        try:
            for df in pd.read_csv(
                args.input,
                header=0,
                names=["rank", "url"],
                skiprows=start_index,
                chunksize=batch_size,
                nrows=crawl_cfg.limit,
            ):
                batch_start_t = time.time()
                print(f"\n{'='*60}")
                print(
                    f"  [Crawler] Processing sites {processed_sites + 1} to {processed_sites + len(df)}"
                )
                urls = df["url"].tolist()
                start_time = datetime.now().strftime("%H:%M")
                print(f"            -> from `{urls[0]}` until `{urls[-1]}`")
                print(f"            -> start time {start_time}")
                print(f"{'='*60}\n")
                for browser in browsers:
                    if len(browsers) > 1:
                        print(f"    [Browser={browser.value}]")

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
                        websites=df["url"].tolist(),
                        output_dir=args.output_dir,
                        browser_cfg=browser_cfg,
                        crawl_cfg=crawl_cfg,
                    )
                print(f"\n{'='*60}")
                print(
                    f"  [Crawler] finished batch {processed_sites // batch_size} in {time.time() - batch_start_t}s"
                )
                processed_sites += len(df)

                # persist progress after every completed batch so a restart
                # can resume from here without manual --skip-first
                os.makedirs(args.output_dir, exist_ok=True)
                with open(progress_file, "w") as _pf:
                    _pf.write(str(processed_sites))

        except asyncio.CancelledError:
            print(
                f"[Crawler] Crawl cancelled at site {processed_sites}. Progress saved."
            )
            raise
        finally:
            loop.remove_signal_handler(signal.SIGTERM)

    asyncio.run(run_all())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted by user")
    except asyncio.CancelledError:
        pass  # clean exit after SIGTERM
