import asyncio
import csv
import re
from typing import Dict, List, Optional, Any
from enum import Enum
from urllib.parse import urlparse
from .chromium_client import ChromiumClient
from .client import Client


class Browser(Enum):
    """Enumeration of supported browser types."""
    CHROMIUM = "chromium"


class ClientUtils:
    """
    Factory class for instantiating browser automation clients.
    
    Provides a centralized way to create and configure different
    browser clients based on the target browser type.
    """
    
    def __init__(self, browser_paths: Dict[str, str]):
        """
        Initialize ClientUtils with browser paths.
        
        Args:
            browser_paths: Dictionary mapping browser names to executable paths
                          (e.g., {"brave": "C:/Program Files/Brave/brave.exe"})
                          Used for custom browser binaries in future implementations.
        """
        self.browser_paths = browser_paths
    
    def get_client(self, browser_type: Browser) -> Client:
        """
        Get a client instance for the specified browser type.
        
        Args:
            browser_type: The type of browser to instantiate
            
        Returns:
            Client instance for the specified browser
            
        Raises:
            ValueError: If the requested browser type is not supported
        """
        
        if browser_type == Browser.CHROMIUM:
            return ChromiumClient()
        else:
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
        headless: Optional[bool] = False
    ) -> None:
        client = ClientUtils(browser_paths={}).get_client(browser)

        async def behavior_callback(client_instance, behavior_params):
            await client_instance._behavior_non_interactive(behavior_params['wait_time_ms'])

        async def on_close_callback(client_instance, close_args):
            await client_instance._on_close_get_cookies_snapshot(
                output_dir=close_args['output_dir'],
                output_name=close_args['output_name'],
                params=close_args['params']
            )

        try:
            await client.visit_page(
                url=url,
                behavior=behavior_callback,
                on_close=on_close_callback,
                params={'wait_time_ms': wait_time_ms},
                output_args={
                    'output_dir': output_dir,
                    'output_name': output_name,
                    'params': params
                },
                timeout_ms=timeout_ms,
                headless=headless
            )
        except Exception as e:
            print(f"Error during page visit: {e}")
            await client._on_close_empty()

    @staticmethod
    async def process_batch(
        websites: List[str],
        output_dir: str = 'cookies_data',
        browser: Browser = Browser.CHROMIUM,
        timeout_ms: int = 10000,
        headless: bool = False,
        limit: Optional[int] = None,
        wait_time_ms: int = 5000,
        concurrency: int = 1
    ) -> None:
        urls = websites[:limit] if limit is not None else websites
        semaphore = asyncio.Semaphore(concurrency)

        async def process_one(url: str) -> None:
            async with semaphore:
                netloc = urlparse(url).netloc or url
                safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', netloc) + '.json'
                print(f"Processing {url} -> {safe_name}")
                await ClientUtils.run_for_page(
                    url=url,
                    wait_time_ms=wait_time_ms,
                    output_dir=output_dir,
                    output_name=safe_name,
                    browser=browser,
                    params={'target_url': url},
                    timeout_ms=timeout_ms,
                    headless=headless
                )

        await asyncio.gather(*[process_one(url) for url in urls])

    @staticmethod
    async def process_batch_from_csv(
        source_file_path: str,
        output_dir: str = 'cookies_data',
        browser: Browser = Browser.CHROMIUM,
        timeout_ms: int = 10000,
        headless: bool = False,
        limit: Optional[int] = None,
        wait_time_ms: int = 5000,
        concurrency: int = 1
    ) -> None:
        _URL_COLUMNS = ('url', 'URL', 'website', 'Website', 'domain', 'Domain')
        websites: List[str] = []
        with open(source_file_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            url_col = next(
                (c for c in _URL_COLUMNS if c in (reader.fieldnames or [])),
                (reader.fieldnames or [None])[0]
            )
            if url_col is None:
                raise ValueError(f"CSV '{source_file_path}' has no columns.")
            for row in reader:
                value = row.get(url_col, '').strip()
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
            concurrency=concurrency
        )
