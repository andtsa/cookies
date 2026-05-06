import asyncio
import json
import os
from typing import Callable, Dict, Any, Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from client import Client


class ChromiumClient(Client):
    """
    Concrete implementation of Client interface using Chromium via Playwright.
    
    Uses Chrome DevTools Protocol (CDP) for advanced automation features
    like cookie management and network monitoring.
    """
    
    def __init__(self):
        self.playwright = None
        self.browser: Browser = None
        self.context: BrowserContext = None
        self.page: Page = None
        self.client = None
    
    async def visit_page(
        self, 
        url: str, 
        behavior: Callable, 
        on_close: Callable, 
        params: Dict[str, Any], 
        output_args: Dict[str, Any],
        timeout_ms: Optional[int] = 10000,
        headless: Optional[bool] = False
    ) -> None:
        """
        Orchestrate the complete page visit workflow.
        
        Executes: setup → navigate → behavior → on_close sequence
        """
        try:
            await self._setup(headless=headless)
            await self._navigate_to_page(url, timeout_ms=timeout_ms)
            await behavior(self, params)
            await on_close(self, output_args)
        except Exception as e:
            print(f"Error during page visit: {e}")
            await self._on_close_empty()
            raise
    
    async def _setup(self, headless: Optional[bool] = False) -> None:
        """
        Initialize Chromium browser with CDP session.
        
        - Launches Chromium (headless=False for visibility)
        - Creates browser context and page
        - Establishes CDP session for advanced control
        - Enables Page and Network domains
        - Clears existing cookies
        """
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=headless)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        self.client = await self.context.new_cdp_session(self.page)
        
        # Enable required CDP domains
        await self.client.send('Page.enable')
        await self.client.send('Network.enable')
        await self.client.send('Network.clearBrowserCookies')

        print("Browser setup complete.")
    
    async def _navigate_to_page(self, url: str, timeout_ms: Optional[int] = 10000) -> None:
        """
        Navigate to the target URL using CDP.
        
        Args:
            url: The target URL to navigate to
            timeout_ms: Timeout in milliseconds for page load
        """
        print(f"Navigating to {url}...")
        await self.page.goto(url, wait_until='load', timeout=timeout_ms)
    
    async def _behavior_non_interactive(self, milliseconds: int) -> None:
        """
        Wait passively for the specified duration.
        
        Args:
            milliseconds: Duration to wait in milliseconds
        """
        seconds = milliseconds / 1000.0
        print(f"Waiting for {seconds} seconds to let trackers load...")
        await asyncio.sleep(seconds)
    
    async def _on_close_get_cookies_snapshot(
        self, 
        output_dir: str, 
        output_name: str, 
        params: Dict[str, Any]
    ) -> None:
        """
        Capture all cookies and save to JSON file with metadata.
        
        Args:
            output_dir: Directory to save the output file
            output_name: Name of the output file
            params: Additional metadata to include in the output JSON
        """
        print('Taking cookie snapshot...')
        response = await self.client.send('Network.getAllCookies')
        cookies = response.get('cookies', [])
        
        print(f"Found {len(cookies)} cookies.")
        
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, output_name)
        else:
            output_path = output_name
        
        output_data = {**params, 'cookies': cookies}       
        print(f"Writing data to {output_path}...")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=4)
        
        print("Scrape complete!")
        
        await self.browser.close()
        await self.playwright.stop()
    
    async def _on_close_empty(self) -> None:
        """
        Default cleanup: close browser without saving data.
        """
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
