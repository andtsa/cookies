import asyncio
import csv
import os
import re
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

from .chromium_client import ChromiumClient
from .client import Client
from .trackers import TrackerList


class Browser(Enum):
    """Enumeration of supported browser types."""

    CHROMIUM   = "chromium"
    CHROME     = "chrome"
    EDGE       = "edge"
    BRAVE      = "brave"
    DUCKDUCKGO = "duckduckgo"


_BROWSER_CHANNEL: Dict[Browser, str] = {
    Browser.CHROME: "chrome",
    Browser.EDGE:   "msedge",
}

_BROWSER_ENV_KEY: Dict[Browser, str] = {
    Browser.BRAVE:      "BRAVE_PATH",
    Browser.DUCKDUCKGO: "DUCKDUCKGO_PATH",
}


class ClientUtils:
    """Factory class for instantiating browser automation clients."""

    def get_client(
        self,
        browser_type: Browser,
        tracker_list: Optional[TrackerList] = None,
    ) -> Client:
        """
        Get a client instance for the specified browser type.

        Raises:
            ValueError: If the requested browser type is not supported
        """
        if browser_type in set(Browser):
            channel         = _BROWSER_CHANNEL.get(browser_type)
            env_key         = _BROWSER_ENV_KEY.get(browser_type)
            executable_path = os.environ.get(env_key) if env_key else None
            if browser_type in {Browser.BRAVE, Browser.DUCKDUCKGO} and not executable_path:
                raise ValueError(f"Executable path for {browser_type.value} not found in environment variable {env_key}")
            return ChromiumClient(
                tracker_list=tracker_list,
                channel=channel,
                executable_path=executable_path,
            )
        raise ValueError(f"Unsupported browser type: {browser_type.value}")

    @staticmethod
    async def run_for_page(
        url: str,
        wait_time_ms: int,
        output_dir: str,
        output_name: str,
        browser: Browser,
        params: Dict[str, Any],
        timeout_ms: Optional[int] = 10000,
        headless: Optional[bool] = False,
        tracker_list: Optional[TrackerList] = None,
    ) -> None:
        client = ClientUtils().get_client(browser, tracker_list=tracker_list)

        async def behavior_callback(client_instance, behavior_params):
            await client_instance._behavior_non_interactive(
                behavior_params["wait_time_ms"]
            )

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
                params={"wait_time_ms": wait_time_ms},
                output_args={
                    "output_dir": output_dir,
                    "output_name": output_name,
                    "params": params,
                },
                timeout_ms=timeout_ms,
                headless=headless,
            )
        except Exception as e:
            print(f"Error during page visit: {e}")
            await client._on_close_empty()

    @staticmethod
    async def process_batch(
        websites: List[str],
        output_dir: str = "cookies_data",
        browser: Browser = Browser.CHROMIUM,
        timeout_ms: int = 10000,
        headless: bool = False,
        limit: Optional[int] = None,
        wait_time_ms: int = 5000,
        concurrency: int = 1,
        tracker_list: Optional[TrackerList] = None,
    ) -> None:
        urls = websites[:limit] if limit is not None else websites
        semaphore = asyncio.Semaphore(concurrency)

        async def process_one(url: str) -> None:
            async with semaphore:
                if not urlparse(url).scheme:
                    url = 'https://' + url
                netloc = urlparse(url).netloc or url
                safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", netloc) + ".json"
                print(f"Processing {url} -> {output_dir}/{safe_name}")
                await ClientUtils.run_for_page(
                    url=url,
                    wait_time_ms=wait_time_ms,
                    output_dir=output_dir,
                    output_name=safe_name,
                    browser=browser,
                    params={"target_url": url},
                    timeout_ms=timeout_ms,
                    headless=headless,
                    tracker_list=tracker_list,
                )

        await asyncio.gather(*[process_one(url) for url in urls])

    @staticmethod
    async def process_batch_from_csv(
        source_file_path: str,
        output_dir: str = "cookies_data",
        browser: Browser = Browser.CHROMIUM,
        timeout_ms: int = 10000,
        headless: bool = False,
        limit: Optional[int] = None,
        wait_time_ms: int = 5000,
        concurrency: int = 1,
        tracker_list: Optional[TrackerList] = None,
    ) -> None:
        _URL_COLUMNS = ("url", "URL", "website", "Website", "domain", "Domain")
        websites: List[str] = []
        with open(source_file_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            url_col = next(
                (c for c in _URL_COLUMNS if c in (reader.fieldnames or [])),
                None
            )
            if url_col is not None:
                for row in reader:
                    value = row.get(url_col, '').strip()
                    if value:
                        websites.append(value)
            else:
                # no recognized header —> treat as headerless CSV, assume domain in column index 1
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
            timeout_ms=timeout_ms,
            headless=headless,
            limit=limit,
            wait_time_ms=wait_time_ms,
            concurrency=concurrency,
            tracker_list=tracker_list,
        )
