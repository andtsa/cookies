import asyncio
from typing import Any, Callable, Dict, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from .client import Client
from .cookies_utils import CookiesUtils
from .tracker_util import TrackerUtil
from .trackers import TrackerList


class ChromiumClient(Client):
    """
    Concrete implementation of Client interface using Chromium via Playwright.

    Uses Chrome DevTools Protocol (CDP) for advanced automation features
    like cookie management and network monitoring.
    """

    def __init__(
        self,
        tracker_list: Optional[TrackerList] = None,
        channel: Optional[str] = None,
        executable_path: Optional[str] = None,
    ):
        self.playwright = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.client = None
        self.tracker_list = tracker_list
        self.tracker_util = TrackerUtil()
        self.channel = channel
        self.executable_path = executable_path

    async def visit_page(
        self,
        url: str,
        behavior: Callable,
        on_close: Callable,
        params: Dict[str, Any],
        output_args: Dict[str, Any],
        timeout_ms: Optional[int] = 10000,
        headless: Optional[bool] = False,
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
        self.browser = await self.playwright.chromium.launch(
            headless=headless,
            channel=self.channel,
            executable_path=self.executable_path,
        )
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        self.client = await self.context.new_cdp_session(self.page)

        # Enable required CDP domains
        await self.client.send("Page.enable")
        await self.client.send("Network.enable")
        await self.client.send("Network.clearBrowserCookies")

        self.client.on("Network.requestWillBeSent", self.tracker_util.on_request_sent)
        self.client.on("Network.responseReceivedExtraInfo", self.tracker_util.on_response_extra)

        print("Browser setup complete.")

    async def _navigate_to_page(
        self, url: str, timeout_ms: Optional[int] = 10000
    ) -> None:
        assert self.page is not None, "Page not initialized"
        """
        Navigate to the target URL using CDP.

        Args:
            url: The target URL to navigate to
            timeout_ms: Timeout in milliseconds for page load
        """
        print(f"Navigating to {url}...")
        await self.page.goto(url, wait_until="load", timeout=timeout_ms)

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
        self, output_dir: str, output_name: str, params: Dict[str, Any]
    ) -> None:
        assert self.context is not None, "Context not initialized"
        assert (
            self.client is not None
            and self.browser is not None
            and self.playwright is not None
        ), "Client not initialized"

        """
        Capture all cookies and save to JSON file with metadata.

        Collects:
        - session vs persistent cookies
        - expiration timestamps
        - cookie lifetime in seconds/days
        - security flags (Secure, HttpOnly, SameSite)
        - is_tracker annotation (if a TrackerList was provided)

        Args:
            output_dir: Directory to save the output file
            output_name: Name of the output file
            params: Additional metadata to include in the output JSON
        """
        print("Taking cookie snapshot...")
        response = await self.client.send("Network.getAllCookies")
        cookies = response.get("cookies", [])
        print(f"Found {len(cookies)} cookies.")

        CookiesUtils.process_and_save(
            cookies, output_dir, output_name, params, self.tracker_list
        )

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
