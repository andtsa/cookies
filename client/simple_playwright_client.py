import asyncio
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from .client import Client
from .cookies_utils import CookiesUtils
from .tracker_util import TrackerUtil
from .trackers import TrackerList

if TYPE_CHECKING:
    from .client_utils import Browser as BrowserEnum


class SimplePlaywrightClient(Client):
    """
    Playwright client for non-Chromium engines (Firefox, WebKit).

    Uses Playwright's cross-browser API for cookie management — no CDP.
    The browser_type parameter selects which Playwright engine to launch.
    """

    def __init__(
        self,
        browser_type: "BrowserEnum",
        tracker_list: Optional[TrackerList] = None,
    ):
        self.browser_type = browser_type
        self.playwright = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.tracker_list = tracker_list
        self.tracker_util = TrackerUtil()

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
        self.playwright = await async_playwright().start()
        launcher = getattr(self.playwright, self.browser_type.value)
        self.browser = await launcher.launch(headless=headless)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        await self.context.clear_cookies()
        self.page.on("request", self.tracker_util.on_request_sent)
        self.page.on("response", self.tracker_util.on_response_extra)
        print(f"{self.browser_type.value.capitalize()} setup complete.")

    async def _navigate_to_page(
        self, url: str, timeout_ms: Optional[int] = 10000
    ) -> None:
        assert self.page is not None, "Page not initialized"
        print(f"Navigating to {url}...")
        await self.page.goto(url, wait_until="load", timeout=timeout_ms)

    async def _behavior_non_interactive(self, milliseconds: int) -> None:
        seconds = milliseconds / 1000.0
        print(f"Waiting for {seconds} seconds to let trackers load...")
        await asyncio.sleep(seconds)

    async def _on_close_get_cookies_snapshot(
        self, output_dir: str, output_name: str, params: Dict[str, Any]
    ) -> None:
        assert self.context is not None, "Context not initialized"
        assert (
            self.browser is not None and self.playwright is not None
        ), "Browser not initialized"

        print(f"Taking {self.browser_type.value.capitalize()} cookie snapshot...")
        cookies = await self.context.cookies()
        print(f"Found {len(cookies)} cookies.")

        CookiesUtils.process_and_save(
            cookies, output_dir, output_name, params, self.tracker_list
        )

        print("Scrape complete!")

        await self.browser.close()
        await self.playwright.stop()

    async def _on_close_empty(self) -> None:
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
