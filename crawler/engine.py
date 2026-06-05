import asyncio
import os
import signal
import time
from datetime import datetime
from typing import Optional

import psutil

from client.api import ClientAPI
from client.config import BrowserConfig, CrawlConfig, Site
from .stats import CrawlStats

# an item in the work queue: (site, browser_cfg) or None sentinel
type Item = tuple[Site, BrowserConfig] | None


class CrawlEngine:
    def __init__(
        self,
        crawl_cfg: CrawlConfig,
        browser_cfgs: list[BrowserConfig],
        batch_size: int,
        start_index: int,
        total_sites: Optional[int],
        progress_file: str,
        input_path: str,
        category: str,
    ):
        self.crawl_cfg = crawl_cfg
        self.browser_cfgs = browser_cfgs
        self.batch_size = batch_size
        self.start_index = start_index
        self.total_sites = total_sites
        self.progress_file = progress_file
        self._input_path = input_path
        self._category = category

        concurrency = crawl_cfg.concurrency
        mb_per_slot = 400 if len(browser_cfgs) == 1 else 500
        self.concurrency = concurrency
        self.max_concurrency = max(
            concurrency,
            int(psutil.virtual_memory().available / (mb_per_slot * 1024 * 1024)),
        )
        self._mb_per_slot = mb_per_slot

        self.stats = CrawlStats(start_index=start_index, concurrency=concurrency)
        # held[0]: net slots held by the monitor (>0 = reduced, <0 = increased)
        self._held: list[int] = [0]
        self._semaphore: asyncio.Semaphore
        self._work_queue: asyncio.Queue[Item]

    async def run(self) -> None:
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

        self._semaphore = asyncio.Semaphore(self.concurrency)
        self._work_queue = asyncio.Queue(
            maxsize=max(self.batch_size * 2, self.max_concurrency * 2)
        )

        throttle_task = asyncio.create_task(self._throttle_monitor())
        heartbeat_task = asyncio.create_task(self._heartbeat())
        worker_tasks = [
            asyncio.create_task(self._worker()) for _ in range(self.max_concurrency)
        ]

        stats_file = os.path.join(self.crawl_cfg.output_dir, "stats.json")
        crawl_start_t = time.time()
        now = datetime.now().strftime("%H:%M")
        print(f"\n{'='*60}")
        print(f"  [Crawler] Starting from site {self.start_index + 1}")
        print(
            f"  | concurrency={self.concurrency} (tuning up to {self.max_concurrency})"
        )
        print(f"  | started at {now} UTC")
        if self.total_sites:
            print(f"  | ~{self.total_sites - self.start_index:,} sites to go")
        print(f"{'='*60}\n")

        processed_sites = self.start_index
        try:
            try:
                yield_sites = self._read_sites()
                async for site, cfg in yield_sites:
                    await self._work_queue.put((site, cfg))
            except asyncio.CancelledError:
                while not self._work_queue.empty():
                    try:
                        self._work_queue.get_nowait()
                        self._work_queue.task_done()
                    except asyncio.QueueEmpty:
                        break
                raise
            finally:
                for _ in range(self.max_concurrency):
                    try:
                        self._work_queue.put_nowait(None)
                    except asyncio.QueueFull:
                        pass

            await asyncio.gather(*worker_tasks, return_exceptions=True)

            elapsed = time.time() - crawl_start_t
            processed_sites = self.start_index + self.stats.completed
            print(f"\n{'='*60}")
            print(
                f"  [Crawler] finished {self.stats.completed} sites in {elapsed:.1f}s"
            )
            print(f"{'='*60}\n")

            os.makedirs(self.crawl_cfg.output_dir, exist_ok=True)
            with open(self.progress_file, "w") as pf:
                pf.write(str(processed_sites))
            self.stats.write(stats_file, total_sites=self.total_sites)

        except asyncio.CancelledError:
            processed_sites = self.start_index + self.stats.completed
            print(
                f"[Crawler] Crawl cancelled at site ~{processed_sites}. Progress saved."
            )
            raise
        finally:
            throttle_task.cancel()
            heartbeat_task.cancel()
            for t in worker_tasks:
                t.cancel()
            await asyncio.gather(
                throttle_task, heartbeat_task, *worker_tasks, return_exceptions=True
            )
            for _ in range(max(0, self._held[0])):
                self._semaphore.release()
            _kill_child_processes()
            loop.remove_signal_handler(signal.SIGTERM)

    async def _read_sites(self):
        """Async generator yielding (Site, BrowserConfig) pairs from the CSV."""
        import pandas as pd

        for df in pd.read_csv(
            self._input_path,
            header=0,
            names=["rank", "url"],
            skiprows=self.start_index,
            chunksize=self.batch_size,
            nrows=self.crawl_cfg.limit,
        ):
            for row in df.itertuples():
                for cfg in self.browser_cfgs:
                    yield Site(
                        url=row.url,
                        rank=row.rank,
                        category=self._category,
                    ), cfg

    async def _worker(self) -> None:
        stats_file = os.path.join(self.crawl_cfg.output_dir, "stats.json")
        while True:
            item = await self._work_queue.get()
            if item is None:
                self._work_queue.task_done()
                return
            site, cfg = item
            try:
                async with self._semaphore:
                    t0 = time.monotonic()
                    result = await ClientAPI.process_url(site, cfg, self.crawl_cfg)
                    elapsed = time.monotonic() - t0
                if result is None:
                    await self.stats.record_skip()
                elif result is False:
                    await self.stats.record_visit(elapsed, success=False)
                else:
                    await self.stats.record_visit(elapsed, success=True)
            except asyncio.CancelledError:
                raise
            finally:
                self._work_queue.task_done()

            if cfg is self.browser_cfgs[-1]:
                n = await self.stats.record_completion()
                if n % self.batch_size == 0:
                    os.makedirs(self.crawl_cfg.output_dir, exist_ok=True)
                    with open(self.progress_file, "w") as pf:
                        pf.write(str(self.start_index + n))
                    self.stats.write(stats_file, total_sites=self.total_sites)
                    print(f"\n  {self.stats.checkpoint_line()}")

    async def _throttle_monitor(self) -> None:
        psutil.cpu_percent()  # first call always returns 0.0
        await asyncio.sleep(5)
        last_spm = 0.0
        last_was_increase = False
        tick = 0
        TUNE_EVERY = 24  # 24 * 5 s = 120 s between tuning decisions

        while True:
            await asyncio.sleep(5)
            tick += 1

            try:
                mem_mb = psutil.virtual_memory().available / (1024 * 1024)
                cpu = psutil.cpu_percent()
            except Exception:
                continue

            effective = self.concurrency - self._held[0]
            under_pressure = mem_mb < 512 or cpu > 90.0

            if under_pressure and effective > 1:
                await self._semaphore.acquire()
                self._held[0] += 1
                effective -= 1
                self.stats.concurrency = effective
                self.stats.active_throttle = True
                last_was_increase = False
                print(
                    f"[Tune] Pressure (mem={mem_mb:.0f} MB, cpu={cpu:.0f}%)"
                    f" -> concurrency={effective}"
                )
                continue

            if not under_pressure and self.stats.active_throttle:
                self.stats.active_throttle = False

            if tick % TUNE_EVERY != 0:
                continue

            current_spm = self.stats.sites_per_min()
            effective = self.concurrency - self._held[0]

            if last_was_increase and current_spm < last_spm * 0.95:
                await self._semaphore.acquire()
                self._held[0] += 1
                effective -= 1
                self.stats.concurrency = effective
                print(
                    f"[Tune] {current_spm:.1f} spm < {last_spm:.1f} after increase"
                    f" => concurrency={effective}"
                )
                last_was_increase = False
            elif effective < self.max_concurrency:
                self._semaphore.release()
                self._held[0] -= 1
                effective += 1
                self.stats.concurrency = effective
                print(f"[Tune] {current_spm:.1f} spm, trying concurrency={effective}")
                last_was_increase = True
            else:
                last_was_increase = False

            last_spm = current_spm

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(60)
            print(f"  {self.stats.checkpoint_line()}")


def _kill_child_processes() -> None:
    """Kill all browser/node child processes still alive after the crawl exits.

    On clean shutdown these will already be gone; this is the safety net for
    interrupted runs where teardown didn't complete.
    """
    try:
        for child in psutil.Process().children(recursive=True):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
    except Exception:
        pass


def kill_orphaned_browsers() -> None:
    """Kill chrome-headless processes left over from a previous interrupted run.

    Orphaned processes have init (PID 1) as their parent because their original
    Python parent has already exited.  Call this at startup before launching any
    new browsers so the old ones don't pile up and freeze the system.
    """
    import getpass

    try:
        current_user = getpass.getuser()
        killed = 0
        for proc in psutil.process_iter(["pid", "name", "username", "ppid"]):
            try:
                if (
                    proc.info["username"] == current_user
                    and "chrome" in (proc.info["name"] or "").lower()
                    and proc.info["ppid"] == 1  # orphaned: parent is init
                ):
                    proc.kill()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if killed:
            print(
                f"[Crawler] Cleaned up {killed} orphaned browser process(es) from previous run"
            )
    except Exception:
        pass
