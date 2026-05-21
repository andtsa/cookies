import asyncio
import csv
import os
import re
from enum import Enum
from typing import List, Optional
from urllib.parse import urlparse

from .chromium_client import ChromiumClient
from .client import Client
from .config import BrowserConfig, CrawlConfig


class Browser(Enum):
    """Enumeration of supported browser types."""

    CHROMIUM = "chromium"


class ClientUtils:
    """Factory and batch-runner for browser automation clients."""

    @staticmethod
    def get_client(browser_type: Browser, cfg: BrowserConfig) -> Client:
        if browser_type == Browser.CHROMIUM:
            return ChromiumClient(cfg=cfg)
        raise ValueError(f"Unsupported browser type: {browser_type.value}")

    @staticmethod
    async def run_for_page(
        url: str,
        output_dir: str,
        output_name: str,
        browser: Browser,
        cfg: BrowserConfig,
    ) -> None:
        client = ClientUtils.get_client(browser, cfg=cfg)

        async def behavior_callback(client_instance):
            await client_instance._behavior_non_interactive()

        async def on_close_callback(client_instance, close_args):
            await client_instance._on_close_get_cookies_snapshot(
                output_dir=close_args["output_dir"],
                output_name=close_args["output_name"],
                params=close_args["params"],
            )

        try:
            await client.visit_page(
                url=url,
                behavior=behavior_callback,
                on_close=on_close_callback,
                output_args={
                    "output_dir": output_dir,
                    "output_name": output_name,
                    "params": {"target_url": url},
                },
            )
        except Exception as e:
            print(f"Error during page visit: {e}")
            await client._on_close_empty()

    @staticmethod
    async def process_batch(
        websites: List[str],
        output_dir: str = "cookies_data",
        browser: Browser = Browser.CHROMIUM,
        browser_cfg: Optional[BrowserConfig] = None,
        crawl_cfg: Optional[CrawlConfig] = None,
    ) -> None:
        if browser_cfg is None:
            browser_cfg = BrowserConfig()
        if crawl_cfg is None:
            crawl_cfg = CrawlConfig()

        urls = websites[: crawl_cfg.limit] if crawl_cfg.limit is not None else websites
        semaphore = asyncio.Semaphore(crawl_cfg.concurrency)

        async def process_one(url: str) -> None:
            async with semaphore:
                if not urlparse(url).scheme:
                    url = "https://" + url
                netloc = urlparse(url).netloc or url
                safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", netloc) + ".json"
                output_path = f"{output_dir}/{safe_name}"

                if not crawl_cfg.overwrite and os.path.exists(output_path):
                    print(f"Skipping {url}, already collected.")
                    return

                print(f"Processing {url} -> {output_path}")
                try:
                    await ClientUtils.run_for_page(
                        url=url,
                        output_dir=output_dir,
                        output_name=safe_name,
                        browser=browser,
                        cfg=browser_cfg,
                    )
                except Exception as e:
                    print(f"Failed for {url}: {e}")
                    if crawl_cfg.failed_sites_path:
                        with open(
                            crawl_cfg.failed_sites_path, "a", encoding="utf-8"
                        ) as f:
                            f.write(f"{url}\n")

                if crawl_cfg.sleep_between_ms > 0:
                    await asyncio.sleep(crawl_cfg.sleep_between_ms / 1000)

        await asyncio.gather(*[process_one(url) for url in urls])

    @staticmethod
    async def process_batch_from_csv(
        source_file_path: str,
        output_dir: str = "cookies_data",
        browser: Browser = Browser.CHROMIUM,
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
                # headerless CSV — assume rank,domain format
                f.seek(0)
                for row in csv.reader(f):
                    if len(row) >= 2:
                        value = row[1].strip()
                        if value:
                            websites.append(value)

        await ClientUtils.process_batch(
            websites=websites,
            output_dir=output_dir,
            browser=browser,
            browser_cfg=browser_cfg,
            crawl_cfg=crawl_cfg,
        )
