import asyncio
import csv
import hashlib
import os
import re
from typing import List, Optional
from urllib.parse import urlparse

from playwright._impl._errors import Error as PlaywrightError

from client.output import Outfile

from .chromium_client import ChromiumClient
from .client import Client
from .config import (
    _BROWSER_CHANNEL,
    _BROWSER_ENV_KEY,
    Browser,
    BrowserConfig,
    CrawlConfig,
    Site,
)
from .simple_playwright_client import SimplePlaywrightClient


class ClientAPI:
    """Factory class for instantiating browser automation clients."""

    def get_client(self, cfg: BrowserConfig) -> Client:
        """
        Get a client instance for the specified browser type.

        Raises:
            ValueError: If the requested browser type is not supported
        """
        if cfg.browser_type in {Browser.FIREFOX, Browser.WEBKIT}:
            return SimplePlaywrightClient(cfg=cfg)
        if cfg.browser_type in set(Browser):
            channel = _BROWSER_CHANNEL.get(cfg.browser_type)
            env_key = _BROWSER_ENV_KEY.get(cfg.browser_type)
            executable_path = os.environ.get(env_key) if env_key else None
            if (
                cfg.browser_type in {Browser.BRAVE, Browser.DUCKDUCKGO}
                and not executable_path
            ):
                raise ValueError(
                    f"Executable path for {cfg.browser_type.value} not found in environment variable {env_key}"
                )
            return ChromiumClient(
                cfg=cfg,
                channel=channel,
                executable_path=executable_path,
            )
        raise ValueError(f"Unsupported browser type: {cfg.browser_type.value}")

    @staticmethod
    async def run_for_page(
        site: Site,
        output: Outfile,
        cfg: BrowserConfig,
    ) -> None:
        client = ClientAPI().get_client(cfg=cfg)

        await client.visit_page(
            site=site,
            output=output,
        )

    @staticmethod
    async def process_url(
        site: Site,
        browser_cfg: BrowserConfig,
        crawl_cfg: CrawlConfig,
    ) -> bool | None:
        """Process a single URL: visit it and write the cookie snapshot to disk.

        Returns:
            None  — skipped (output file already exists)
            True  — visited successfully
            False — visit failed (error logged / written to failed_sites)
        """
        if not urlparse(site.url).scheme:
            site.url = "https://" + site.url
        netloc = urlparse(site.url).netloc or site.url
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", netloc) + ".json"
        # shard into 256 subdirectories by hash to avoid 1M files in
        # one directory, which can crash linux filesystems
        shard = hashlib.md5(netloc.encode()).hexdigest()[:2]
        specific_dir = (
            f"{crawl_cfg.output_dir}/{browser_cfg.browser_type.value}/{shard}"
        )
        output_path = f"{specific_dir}/{safe_name}"

        if not crawl_cfg.overwrite and os.path.exists(output_path):
            print(f"[{netloc}] skipping (already collected)")
            return None

        print(f"[{netloc}] crawling -> {output_path}")
        result = True
        try:
            await ClientAPI.run_for_page(
                site=site,
                output=Outfile(
                    dir=specific_dir,
                    name=safe_name,
                    target_url=site.url,
                    country=crawl_cfg.country,
                    browser=browser_cfg.browser_type.value,
                    rank=site.rank,
                    category=site.category,
                ),
                cfg=browser_cfg,
            )
        except BaseException as e:
            result = False
            print(f"[{netloc}] error: {e}")
            if crawl_cfg.failed_sites_path:
                try:
                    _write_failed_site(
                        path=crawl_cfg.failed_sites_path,
                        site=site,
                        error=e,
                    )
                except OSError as write_err:
                    print(
                        f"[{netloc}] warning: could not write to failed_sites file: {write_err}\n    original exception: {e}"
                    )

        if crawl_cfg.sleep_between_ms > 0:
            await asyncio.sleep(crawl_cfg.sleep_between_ms / 1000)

        return result

    @staticmethod
    async def process_batch(
        websites: List[Site],
        browser_cfg: Optional[BrowserConfig] = None,
        crawl_cfg: Optional[CrawlConfig] = None,
    ) -> None:
        if browser_cfg is None:
            browser_cfg = BrowserConfig()
        if crawl_cfg is None:
            crawl_cfg = CrawlConfig()

        loop = asyncio.get_event_loop()
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

        sites = websites[: crawl_cfg.limit] if crawl_cfg.limit is not None else websites
        semaphore = asyncio.Semaphore(crawl_cfg.concurrency)

        async def process_one(site: Site) -> None:
            async with semaphore:
                await ClientAPI.process_url(site, browser_cfg, crawl_cfg)

        await asyncio.gather(
            *[process_one(site) for site in sites], return_exceptions=True
        )

    @staticmethod
    async def process_batch_from_csv(
        source_file_path: str,
        browser_cfg: Optional[BrowserConfig] = None,
        crawl_cfg: Optional[CrawlConfig] = None,
    ) -> None:
        _URL_COLUMNS = ("url", "URL", "website", "Website", "domain", "Domain")
        websites: List[Site] = []
        with open(source_file_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            url_col = next(
                (c for c in _URL_COLUMNS if c in (reader.fieldnames or [])),
                None,
            )
            if url_col is not None:
                for i, row in enumerate(reader):
                    value = row.get(url_col, "").strip()
                    if value:
                        websites.append(Site(url=value, rank=i, category=None))
            else:
                f.seek(0)
                for i, row in enumerate(csv.reader(f)):
                    if crawl_cfg and i < crawl_cfg.start_index:
                        continue
                    if len(row) >= 2:
                        value = row[1].strip()
                        if value:
                            websites.append(Site(url=value, rank=i, category=None))

        await ClientAPI.process_batch(
            websites=websites,
            browser_cfg=browser_cfg,
            crawl_cfg=crawl_cfg,
        )


def _write_failed_site(path: str, site: Site, error: BaseException) -> None:
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        reason, msg = get_error_reason(error)
        writer.writerow(
            [
                site.rank,
                site.url,
                reason,
                msg,
            ]
        )


def get_error_reason(error: BaseException) -> tuple[str, str]:
    msg = str(error)

    match = re.search(r"net::(ERR_[A-Z_]+)", msg)

    msg = msg.strip()[:100].replace("\n", " ")
    if match:
        return match.group(1), "network error"

    # asyncio.TimeoutError carries our descriptive label as its message
    # (e.g. "TIMEOUT:browser_setup", "TIMEOUT:Network.getAllCookies").
    # Playwright's own TimeoutError shows up as "Timeout NNNms exceeded" in msg.
    if isinstance(error, asyncio.TimeoutError):
        return "ASYNCIO_TIMEOUT" if msg else "TIMEOUT", msg
    if "Timeout" in msg:
        return "TIMEOUT", msg

    return type(error).__name__, msg
