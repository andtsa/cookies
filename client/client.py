import asyncio
from abc import ABC, abstractmethod
from typing import Optional, cast
from urllib.parse import urlparse

import psutil
from playwright._impl._errors import Error as PlaywrightError
from playwright.async_api import Browser, Playwright
import tldextract

from client.output import Outfile

from .config import BrowserConfig, Site
from .trackers.js import CookieReadInterceptor


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
        self._request_context: dict[str, dict] = {}
        self._cookie_set_context: dict[tuple, dict] = {}
        self._is_closed: bool = False
        self._url: str = ""
        self.page_html: str = ""
        self._playwright_node_pid: Optional[int] = None

    def _log(self, msg: str) -> None:
        host = urlparse(self._url).netloc or self._url
        print(f"[{host}] {msg}")

    # shared methods

    async def visit_page(
        self,
        site: Site,
        output: Outfile,
    ) -> None:
        """setup, navigate, behavior, on_close"""
        self._url = site.url
        try:
            await self._setup(url=site.url)
            self._record_node_pid()
            await self._navigate_to_page(site.url)
            await self._behavior_non_interactive()
            await self._on_close_get_cookies_snapshot(output, site)
        except BaseException:
            try:
                await asyncio.shield(self._on_close_empty())
            except (asyncio.CancelledError, Exception):
                pass
            raise

    def _record_node_pid(self) -> None:
        try:
            if self.playwright:
                self._playwright_node_pid = (
                    self.playwright._impl_obj._connection._transport._proc.pid
                )
        except Exception or AttributeError:
            pass

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
        """Close browser and stop Playwright after a successful snapshot.

        Both browser.close() and playwright.stop() can hang indefinitely if the
        browser process becomes unresponsive (e.g. after a heavy or crashing
        page). We guard each with asyncio.wait_for so a stuck teardown never
        blocks the whole crawl.

        this method is idempotent
        """
        timeout = self.cfg.timeout_ms / 1000.0
        if self._is_closed:
            return
        self._is_closed = True

        if self._cookie_read_interceptor is not None:
            self._cookie_read_interceptor.close()

        if self.context:
            try:
                await asyncio.wait_for(self.context.close(), timeout=timeout)
            except asyncio.TimeoutError:
                self._log(f"context.close() timed out after {timeout}s")
            except PlaywrightError:
                pass  # browser already gone

        if self.browser:
            try:
                await asyncio.wait_for(
                    cast(Browser, self.browser).close(), timeout=timeout
                )
            except asyncio.TimeoutError:
                self._log(
                    f"browser.close() timed out after {timeout}s, killing orphaned browser processes"
                )
                if self._playwright_node_pid is not None:
                    try:
                        node_proc = psutil.Process(self._playwright_node_pid)
                        for child in node_proc.children(recursive=True):
                            child.kill()
                        node_proc.kill()
                    except psutil.NoSuchProcess:
                        pass
                    except psutil.Error:
                        pass
                    try:
                        await asyncio.wait_for(
                            cast(Playwright, self.playwright).stop(), timeout=2.0
                        )
                    except Exception:
                        pass
                    self.playwright = None
            except PlaywrightError:
                pass

        if self.playwright:
            try:
                await asyncio.wait_for(
                    cast(Playwright, self.playwright).stop(), timeout=timeout
                )
            except asyncio.TimeoutError:
                self._log(f"playwright.stop() timed out after {timeout}s")
            except PlaywrightError:
                pass

    # engine-specific abstract hooks

    @abstractmethod
    async def _setup(self, url: str) -> None:
        """Launch the browser, create context/page, register event listeners."""

    @abstractmethod
    async def _navigate_to_page(self, url: str) -> None:
        """Navigate to url, honouring cfg.timeout_ms."""

    @abstractmethod
    async def _on_close_get_cookies_snapshot(self, output: Outfile, site: Site) -> None:
        """Collect cookies, save to JSON, then call _teardown()."""
