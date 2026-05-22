from typing import Optional

import tldextract
from playwright.async_api import async_playwright

from .client import Client
from .config import BrowserConfig
from .output import Outfile, OutputFormat
from .util import _parse_set_cookie_name


class ChromiumClient(Client):
    """
    Concrete implementation of Client interface using Chromium via Playwright.
    """

    def __init__(
        self,
        cfg: BrowserConfig,
        channel: Optional[str] = None,
        executable_path: Optional[str] = None,
    ):
        super().__init__(cfg)
        self.client = None  # CDP session
        self._request_context: dict[str, dict] = {}
        self.channel = channel
        self.executable_path = executable_path

    async def _setup(self, url: str) -> None:
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.cfg.headless,
            channel=self.channel,
            executable_path=self.executable_path,
        )
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        self.client = await self.context.new_cdp_session(self.page)

        await self.client.send("Page.enable")
        await self.client.send("Network.enable")
        await self.client.send("Network.clearBrowserCookies")

        self.client.on("Network.requestWillBeSent", self._on_request_sent)
        self.client.on("Network.responseReceivedExtraInfo", self._on_response_extra)

        await self._attach_cookie_read_interceptor(url)

    async def _navigate_to_page(self, url: str) -> None:
        assert self.page is not None, "Page not initialized"
        await self.page.goto(url, wait_until="load", timeout=self.cfg.timeout_ms)

    async def _on_close_get_cookies_snapshot(self, output: Outfile) -> None:
        assert self.context is not None, "Context not initialized"
        assert self.client is not None and self.browser is not None, "Not initialized"

        response = await self.client.send("Network.getAllCookies")
        cookies = response.get("cookies", [])

        OutputFormat.process_and_save(
            cookies,
            self._cookie_set_context,
            self._request_log,
            output,
            self.cfg.tracker_list,
            self._cookie_read_interceptor,
        )

        self._log(f"{len(cookies)} cookies -> {output.path}")
        await self._teardown()

    # CDP event handlers

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
        if self.cfg.matcher and request_url and document_url:
            result = self.cfg.matcher.match(request_url, document_url, cdp_type)
            easyprivacy_match = result.to_dict()

        self._request_log.append(
            {
                "url": request_url,
                "type": cdp_type,
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

        # CDP joins multiple Set-Cookie values with \n
        for raw_cookie in set_cookie.split("\n"):
            name = _parse_set_cookie_name(raw_cookie)
            if not name:
                continue
            key = (name, request_domain)
            self._cookie_set_context[key] = {
                "set_by_request_url": ctx["url"],
                "set_by_request_type": ctx["type"],
                "set_by_initiator": ctx["initiator"],
                "is_third_party_set": request_domain != page_domain,
            }
