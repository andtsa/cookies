import asyncio
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional, cast
from urllib.parse import urlparse

from playwright.async_api import Browser, Playwright
import tldextract

from client.output import Outfile

from .config import BrowserConfig
from .trackers.reads import CookieReadInterceptor


class Client(ABC):
    """
    Abstract base class for browser automation clients.

    Concrete methods here are identical across all browser engines.
    Subclasses implement the three abstract hooks that are engine-specific:
    _setup, _navigate_to_page, and _on_close_get_cookies_snapshot.
    """

    def __init__(self, cfg: BrowserConfig) -> None:
        self.cfg = cfg
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._cookie_read_interceptor: Optional[CookieReadInterceptor] = None
        self._request_log: list[dict] = []
        self._cookie_set_context: dict[tuple, dict] = {}
        self._is_closed: bool = False
        self._url: str = ""

    def _log(self, msg: str) -> None:
        host = urlparse(self._url).netloc or self._url
        print(f"[{host}] {msg}")

    # shared methods

    async def visit_page(
        self,
        url: str,
        behavior: Callable,
        on_close: Callable,
        output: Outfile,
    ) -> None:
        """setup, navigate, behavior, on_close"""
        self._url = url
        try:
            await self._setup(url=url)
            await self._navigate_to_page(url)
            await behavior(self)
            await on_close(self, output)
        except Exception:
            await self._on_close_empty()
            raise

    async def _behavior_non_interactive(self) -> None:
        await asyncio.sleep(self.cfg.wait_time_ms / 1000.0)

    async def _on_close_empty(self) -> None:
        # do nothing
        await self._teardown()

    async def _attach_cookie_read_interceptor(self, url: str) -> None:
        """Attach JS document.cookie read interception if enabled in cfg."""
        if self.cfg.intercept_cookie_reads and self.page is not None:
            domain = tldextract.extract(url).registered_domain or url
            self._cookie_read_interceptor = CookieReadInterceptor(visited_domain=domain)
            await self._cookie_read_interceptor.attach(self.page)

    async def _teardown(self) -> None:
        """Close browser and stop Playwright after a successful snapshot."""
        self._is_closed = True
        if self._cookie_read_interceptor is not None:
            self._cookie_read_interceptor.close()
        if self.browser:
            await cast(Browser, self.browser).close()
        if self.playwright:
            await cast(Playwright, self.playwright).stop()
    # engine-specific abstract hooks

    @abstractmethod
    async def _setup(self, url: str) -> None:
        """Launch the browser, create context/page, register event listeners."""

    @abstractmethod
    async def _navigate_to_page(self, url: str) -> None:
        """Navigate to url, honouring cfg.timeout_ms."""

    @abstractmethod
    async def _on_close_get_cookies_snapshot(self, output: Outfile) -> None:
        """Collect cookies, save to JSON, then call _teardown()."""
