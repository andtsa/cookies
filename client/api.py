import asyncio
import csv
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
        url: str,
        output: Outfile,
        cfg: BrowserConfig,
    ) -> None:
        client = ClientAPI().get_client(cfg=cfg)

        async def behavior_callback(client_instance: Client):
            await client_instance._behavior_non_interactive()

        async def on_close_callback(client_instance: Client, output: Outfile):
            await client_instance._on_close_get_cookies_snapshot(output)

        await client.visit_page(
            url=url,
            behavior=behavior_callback,
            on_close=on_close_callback,
            output=output,
        )

    @staticmethod
    async def process_batch(
        websites: List[str],
        output_dir: str = "cookies_data",
        browser_cfg: Optional[BrowserConfig] = None,
        crawl_cfg: Optional[CrawlConfig] = None,
    ) -> None:
        if browser_cfg is None:
            browser_cfg = BrowserConfig()
        if crawl_cfg is None:
            crawl_cfg = CrawlConfig()

        # Playwright internally creates fire-and-forget asyncio tasks for CDP
        # protocol calls (Channel.send). These tasks can fail with Playwright
        # protocol errors (e.g. TargetClosedError when the browser closes, or
        # "object has been collected to prevent unbounded heap growth" under
        # memory pressure) and emit "Task exception was never retrieved"
        # warnings. All are expected, benign noise — suppress them.
        loop = asyncio.get_event_loop()
        _original_handler = loop.get_exception_handler()

        def _suppress_playwright_channel_errors(
            loop: asyncio.AbstractEventLoop, context: dict
        ) -> None:
            if context.get(
                "message"
            ) == "Task exception was never retrieved" and isinstance(
                context.get("exception"), PlaywrightError
            ):
                return
            (
                _original_handler(loop, context)
                if _original_handler
                else loop.default_exception_handler(context)
            )

        loop.set_exception_handler(_suppress_playwright_channel_errors)

        urls = websites[: crawl_cfg.limit] if crawl_cfg.limit is not None else websites
        semaphore = asyncio.Semaphore(crawl_cfg.concurrency)

        async def process_one(url: str) -> None:
            async with semaphore:
                if not urlparse(url).scheme:
                    url = "https://" + url
                netloc = urlparse(url).netloc or url
                safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", netloc) + ".json"
                specific_dir = f"{output_dir}/{browser_cfg.browser_type.value}"
                output_path = f"{specific_dir}/{safe_name}"

                if not crawl_cfg.overwrite and os.path.exists(output_path):
                    print(f"[{netloc}] skipping (already collected)")
                    return

                print(f"[{netloc}] crawling -> {output_path}")
                try:
                    await ClientAPI.run_for_page(
                        url=url,
                        output=Outfile(
                            dir=specific_dir, name=safe_name, target_url=url
                        ),
                        cfg=browser_cfg,
                    )
                except Exception as e:
                    print(f"[{netloc}] error: {e}")
                    if crawl_cfg.failed_sites_path:
                        _write_failed_site(
                            path=crawl_cfg.failed_sites_path,
                            url=url,
                            error=e,
                        )

                if crawl_cfg.sleep_between_ms > 0:
                    await asyncio.sleep(crawl_cfg.sleep_between_ms / 1000)

        await asyncio.gather(*[process_one(url) for url in urls])

    @staticmethod
    async def process_batch_from_csv(
        source_file_path: str,
        output_dir: str = "cookies_data",
        browser_cfg: Optional[BrowserConfig] = None,
        crawl_cfg: Optional[CrawlConfig] = None,
    ) -> None:
        _URL_COLUMNS = ("url", "URL", "website", "Website", "domain", "Domain")
        websites: List[str] = []
        with open(source_file_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            url_col = next(
                (c for c in _URL_COLUMNS if c in (reader.fieldnames or [])),
                None,
            )
            if url_col is not None:
                for row in reader:
                    value = row.get(url_col, "").strip()
                    if value:
                        websites.append(value)
            else:
                f.seek(0)
                for i, row in enumerate(csv.reader(f)):
                    if crawl_cfg and i < crawl_cfg.start_index:
                        continue
                    if len(row) >= 2:
                        value = row[1].strip()
                        if value:
                            websites.append(value)

        await ClientAPI.process_batch(
            websites=websites,
            output_dir=output_dir,
            browser_cfg=browser_cfg,
            crawl_cfg=crawl_cfg,
        )



def _write_failed_site(path: str, url: str, error: Exception) -> None:
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            url,
            get_error_reason(error),
        ])


def get_error_reason(error: Exception) -> str:
    msg = str(error)

    match = re.search(r"net::(ERR_[A-Z_]+)", msg)
    if match:
        return match.group(1)

    if "Timeout" in msg:
        return "TIMEOUT"

    return type(error).__name__