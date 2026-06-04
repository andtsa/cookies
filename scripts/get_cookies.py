import argparse
import asyncio
import os
import signal
import sys
import pandas as pd
import psutil
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from classifier.sensitive_classifier import SensitiveClassifier
from client.api import Browser, ClientAPI
from client.config import BrowserConfig, CrawlConfig, Site
from client.trackers import Detections, TrackerList
from client.trackers.matcher import EasyPrivacyMatcher
from crawl_stats import CrawlStats

# an item in the work queue (site, browser_cfg)
type Item = tuple[Site, BrowserConfig] | None


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

    # auto-tune concurrency when the user hasn't explicitly set it.
    # The workload is I/O-bound (waiting for pages to load), so RAM is the
    # real constraint — not CPU cores.
    concurrency_explicit = any(a in sys.argv for a in ("--concurrency", "-c"))
    if not concurrency_explicit and not args.force_concurrency:
        cores = os.cpu_count() or 1
        cpu_based = max(1, cores - 1)
        mem = psutil.virtual_memory()
        # each concurrency slot = 1 browser process; add headroom for multi-browser overlap
        mb_per_slot = 400 if len(args.browsers) == 1 else 500
        mem_based = max(1, int(mem.available / (mb_per_slot * 1024 * 1024)))
        # CPU cores anchor the default (Chromium is not purely I/O-bound — JS
        # execution and scheduler overhead make cores - 1 a reliable heuristic);
        # RAM caps it as a safety check on memory-constrained machines
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
        # warn but don't cap: page visits are I/O-bound so more workers than
        # cores is normal and beneficial. Use --force-concurrency to silence.
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

    # auto-resume: if --skip-first was not explicitly set and a progress file
    # exists in the output directory, pick up from where the last run stopped
    progress_file = os.path.join(crawl_cfg.output_dir, "progress.txt")
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
        from playwright._impl._errors import Error as PlaywrightError

        loop = asyncio.get_running_loop()
        main_task = asyncio.current_task()

        def _on_sigterm():
            print("\n[Crawler] Received SIGTERM, cancelling crawl...")
            if main_task:
                main_task.cancel()

        loop.add_signal_handler(signal.SIGTERM, _on_sigterm)

        _original_handler = loop.get_exception_handler()

        def _suppress_playwright_channel_errors(
            loop: asyncio.AbstractEventLoop, context: dict
        ) -> None:
            if isinstance(context.get("exception"), PlaywrightError):
                return
            (
                _original_handler(loop, context)
                if _original_handler
                else loop.default_exception_handler(context)
            )

        loop.set_exception_handler(_suppress_playwright_channel_errors)

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

        semaphore = asyncio.Semaphore(concurrency)
        stats = CrawlStats(start_index=start_index, concurrency=concurrency)
        stats_file = os.path.join(crawl_cfg.output_dir, "stats.json")
        total_sites = args.limit or (
            1000000 if "list_websites_1M.csv" in args.input else None
        )

        # Upper bound for concurrency tuning: RAM-based limit.
        # Pre-spawn this many workers so tuning can increase concurrency
        # immediately by releasing semaphore slots into an already-waiting pool.
        mb_per_slot = 400 if len(browser_cfgs) == 1 else 500
        max_concurrency = max(
            concurrency,
            int(psutil.virtual_memory().available / (mb_per_slot * 1024 * 1024)),
        )

        # held[0]: net slots held by the monitor (>0 = reduced, <0 = increased).
        # Exposed as a list so the outer finally can release them without a closure.
        held: list[int] = [0]

        # Queue large enough to buffer normal work plus max_concurrency sentinels.
        work_queue: asyncio.Queue[Item] = asyncio.Queue(
            maxsize=max(args.batch_size * 2, max_concurrency * 2)
        )

        async def _throttle_monitor() -> None:
            psutil.cpu_percent()  # prime the cache (first call always returns 0.0)
            await asyncio.sleep(5)
            last_spm = 0.0
            last_was_increase = False
            tick = 0
            TUNE_EVERY = 24  # 24 × 5 s = 120 s between tuning decisions

            while True:
                await asyncio.sleep(5)
                tick += 1

                try:
                    mem_mb = psutil.virtual_memory().available / (1024 * 1024)
                    cpu = psutil.cpu_percent()
                except Exception:
                    continue

                effective = concurrency - held[0]
                under_pressure = mem_mb < 512 or cpu > 90.0

                # fast path: react to pressure immediately
                if under_pressure and effective > 1:
                    await semaphore.acquire()
                    held[0] += 1
                    effective -= 1
                    stats.concurrency = effective
                    stats.active_throttle = True
                    last_was_increase = False
                    print(
                        f"[Tune] Pressure (mem={mem_mb:.0f} MB, cpu={cpu:.0f}%)"
                        f" → concurrency={effective}"
                    )
                    continue  # skip tuning tick while under pressure

                if not under_pressure and stats.active_throttle:
                    stats.active_throttle = False

                # slow path: hill-climb every TUNE_EVERY ticks
                if tick % TUNE_EVERY != 0:
                    continue

                current_spm = stats.sites_per_min()
                effective = concurrency - held[0]

                if last_was_increase and current_spm < last_spm * 0.95:
                    # throughput dropped after an increase → undo it
                    await semaphore.acquire()
                    held[0] += 1
                    effective -= 1
                    stats.concurrency = effective
                    print(
                        f"[Tune] {current_spm:.1f} spm < {last_spm:.1f} after increase"
                        f" → concurrency={effective}"
                    )
                    last_was_increase = False
                elif effective < max_concurrency:
                    # throughput stable or improved → try one step higher
                    semaphore.release()
                    held[0] -= 1
                    effective += 1
                    stats.concurrency = effective
                    print(
                        f"[Tune] {current_spm:.1f} spm, trying concurrency={effective}"
                    )
                    last_was_increase = True
                else:
                    last_was_increase = False

                last_spm = current_spm

        async def _heartbeat() -> None:
            while True:
                await asyncio.sleep(60)
                print(f"  {stats.checkpoint_line()}")

        async def worker() -> None:
            while True:
                item = await work_queue.get()
                if item is None:  # end-of-stream sentinel
                    work_queue.task_done()
                    return
                site, cfg = item
                try:
                    async with semaphore:
                        t0 = time.monotonic()
                        result = await ClientAPI.process_url(site, cfg, crawl_cfg)
                        elapsed = time.monotonic() - t0
                    if result is None:  # skipped (already collected)
                        await stats.record_skip()
                    elif result is False:  # visit failed
                        await stats.record_visit(elapsed, success=False)
                    else:  # success
                        await stats.record_visit(elapsed, success=True)
                except asyncio.CancelledError:
                    raise
                finally:
                    work_queue.task_done()

                if cfg is browser_cfgs[-1]:
                    n = await stats.record_completion()
                    if n % args.batch_size == 0:
                        os.makedirs(crawl_cfg.output_dir, exist_ok=True)
                        with open(progress_file, "w") as _pf:
                            _pf.write(str(start_index + n))
                        stats.write(stats_file, total_sites=total_sites)
                        print(f"\n  {stats.checkpoint_line()}")

        throttle_task = asyncio.create_task(_throttle_monitor())
        heartbeat_task = asyncio.create_task(_heartbeat())
        # Spawn max_concurrency workers: idle ones wait on the queue/semaphore
        # and are picked up immediately when the tuner opens a new slot.
        worker_tasks = [asyncio.create_task(worker()) for _ in range(max_concurrency)]

        crawl_start_t = time.time()
        print(f"\n{'='*60}")
        print(
            f"  [Crawler] Starting from site {start_index + 1}"
            f"  |  concurrency={concurrency} (tuning up to {max_concurrency})"
        )
        print(f"            -> {datetime.now().strftime('%H:%M')}")
        if total_sites:
            print(f"            -> ~{total_sites - start_index:,} sites to go")
        print(f"{'='*60}\n")

        processed_sites = start_index
        try:
            try:
                for df in pd.read_csv(
                    args.input,
                    header=0,
                    names=["rank", "url"],
                    skiprows=start_index,
                    chunksize=args.batch_size,
                    nrows=crawl_cfg.limit,
                ):
                    for row in df.itertuples():
                        url = row.url
                        rank = row.rank
                        for cfg in browser_cfgs:
                            await work_queue.put(
                                (Site(url=url, rank=rank, category=args.category), cfg)
                            )
            except asyncio.CancelledError:
                # drain pending items so task_done() accounting stays consistent
                while not work_queue.empty():
                    try:
                        work_queue.get_nowait()
                        work_queue.task_done()
                    except asyncio.QueueEmpty:
                        break
                raise
            finally:
                # one sentinel per worker so every worker exits cleanly
                for _ in range(max_concurrency):
                    try:
                        work_queue.put_nowait(None)
                    except asyncio.QueueFull:
                        pass

            await asyncio.gather(*worker_tasks, return_exceptions=True)

            elapsed = time.time() - crawl_start_t
            processed_sites = start_index + stats.completed
            print(f"\n{'='*60}")
            print(f"  [Crawler] finished {stats.completed} sites in {elapsed:.1f}s")
            print(f"{'='*60}\n")

            # final checkpoint
            os.makedirs(crawl_cfg.output_dir, exist_ok=True)
            with open(progress_file, "w") as _pf:
                _pf.write(str(processed_sites))
            stats.write(stats_file, total_sites=total_sites)

        except asyncio.CancelledError:
            processed_sites = start_index + stats.completed
            print(
                f"[Crawler] Crawl cancelled at site ~{processed_sites}. Progress saved."
            )
            raise
        finally:
            throttle_task.cancel()
            heartbeat_task.cancel()
            # suppress CancelledError from background tasks
            await asyncio.gather(throttle_task, heartbeat_task, return_exceptions=True)
            # release any slots held by the monitor so blocked workers can exit
            for _ in range(max(0, held[0])):
                semaphore.release()
            loop.remove_signal_handler(signal.SIGTERM)

    asyncio.run(run_all())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted by user")
    except asyncio.CancelledError:
        pass  # clean exit after SIGTERM
