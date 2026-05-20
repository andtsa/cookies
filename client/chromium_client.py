import asyncio
from typing import Any, Callable, Dict, Optional

import tldextract
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from client.trackers.matcher import EasyPrivacyMatcher
from client.trackers.reads import CookieReadInterceptor

from .client import Client
from .cookies_utils import CookiesUtils
from .trackers import TrackerList
from .util import _parse_set_cookie_name


class ChromiumClient(Client):
    """
    Concrete implementation of Client interface using Chromium via Playwright.

    Uses Chrome DevTools Protocol (CDP) for advanced automation features
    like cookie management and network monitoring.
    """

    def __init__(
        self,
        tracker_list: Optional[TrackerList] = None,
        matcher=None,
        intercept_cookie_reads: bool = False,
    ):
        self.playwright = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.client = None
        self.tracker_list = tracker_list

        self.easyprivacy_matcher: EasyPrivacyMatcher | None = matcher

        self._intercept_cookie_reads: bool = intercept_cookie_reads
        self._cookie_read_interceptor: CookieReadInterceptor | None = None
        self._request_context: dict[str, dict] = {}
        self._cookie_set_context: dict[tuple, dict] = {}
        self._request_log: list[dict] = []

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
            await self._setup(url=url, headless=headless)
            await self._navigate_to_page(url, timeout_ms=timeout_ms)
            await behavior(self, params)
            await on_close(self, output_args)
        except Exception as e:
            print(f"Error in chromium client during visit_page:\n\t{e}")
            await self._on_close_empty()
            raise

    async def _setup(
        self,
        url: str,
        headless: Optional[bool] = False,
    ) -> None:
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
        await self.client.send("Page.enable")
        await self.client.send("Network.enable")
        await self.client.send("Network.clearBrowserCookies")

        self.client.on("Network.requestWillBeSent", self._on_request_sent)
        self.client.on("Network.responseReceivedExtraInfo", self._on_response_extra)

        if self._intercept_cookie_reads:
            domain = tldextract.extract(url).registered_domain or url
            self._cookie_read_interceptor = CookieReadInterceptor(visited_domain=domain)
            await self._cookie_read_interceptor.attach(self.page)

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

    async def _on_request_sent(self, event: dict) -> None:
        rid = event["requestId"]
        request_url = event["request"]["url"]
        document_url = event.get("documentURL", "")
        cdp_type = event.get("type", "")

        self._request_context[rid] = {
            "url": request_url,
            "document_url": document_url,
            "type": cdp_type,
            "initiator": (event.get("initiator") or {}).get("url", ""),
        }

        easyprivacy_match = {"matched": False}
        if self.easyprivacy_matcher and request_url and document_url:
            result = self.easyprivacy_matcher.match(request_url, document_url, cdp_type)
            easyprivacy_match = result.to_dict()

        self._request_log.append(
            {
                "request_id": rid,
                "url": request_url,
                "type": cdp_type,
                # "is_third_party":   self._is_third_party(request_url, document_url),
                "easyprivacy": easyprivacy_match,
            }
        )

    async def _on_response_extra(self, event: dict) -> None:
        rid = event["requestId"]
        headers = event.get("headers", {})

        set_cookie = next(
            (v for k, v in headers.items() if k.lower() == "set-cookie"), None
        )
        if not set_cookie:
            return

        ctx = self._request_context.get(rid)
        if not ctx or not ctx["url"] or not ctx["document_url"]:
            return

        request_domain = tldextract.extract(ctx["url"]).registered_domain
        page_domain = tldextract.extract(ctx["document_url"]).registered_domain

        if not request_domain or not page_domain:
            return

        # Parse one or more cookies from the header (CDP joins them with \n)
        for raw_cookie in set_cookie.split("\n"):
            name = _parse_set_cookie_name(raw_cookie)
            if not name:
                continue

            # Key: (name, request_domain) — same cookie set by different domains
            # should produce separate entries
            key = (name, request_domain)
            self._cookie_set_context[key] = {
                "set_by_request_url": ctx["url"],
                "set_by_request_type": ctx["type"],  # "XHR", "Image", "Ping", ...
                "set_by_initiator": ctx["initiator"],  # script URL that triggered this
                "is_third_party_set": request_domain != page_domain,
            }

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
            cookies,
            self._cookie_set_context,
            self._request_log,
            output_dir,
            output_name,
            params,
            self.tracker_list,
            self._cookie_read_interceptor,
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
