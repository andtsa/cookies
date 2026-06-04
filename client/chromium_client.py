from typing import Optional

import tldextract
from playwright.async_api import async_playwright

from .client import Client
from .config import BrowserConfig, Site
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
        self.client.on("Network.responseReceived", self._on_response_received)
        self.client.on("Network.responseReceivedExtraInfo", self._on_response_extra)

        await self._attach_cookie_read_interceptor(url)

    async def _navigate_to_page(self, url: str) -> None:
        assert self.page is not None, "Page not initialized"
        await self.page.goto(url, wait_until="load", timeout=self.cfg.timeout_ms)

    async def _on_close_get_cookies_snapshot(self, output: Outfile, site: Site) -> None:
        assert self.context is not None, "Context not initialized"
        assert self.client is not None and self.browser is not None, "Not initialized"

        response = await self.client.send("Network.getAllCookies")
        cookies = response.get("cookies", [])

        if self.cfg.classifier:
            sensitivity_result = self.cfg.classifier.classify_html(
                await self.page.content()
            )
        else:
            sensitivity_result = None

        OutputFormat.process_and_save(
            site,
            cookies,
            self._cookie_set_context,
            self._request_log,
            output,
            self.cfg.tracker_list,
            self._cookie_read_interceptor,
            sensitivity_result,
        )

        self._log(f"{len(cookies)} cookies -> {output.path}")
        await self._teardown()

    # CDP event handlers

    async def _on_request_sent(self, event: dict) -> None:
        rid = event["requestId"]
        request_url = event["request"]["url"]
        document_url = event.get("documentURL", "")
        cdp_type = event.get("type", "")
        initiator = (event.get("initiator") or {}).get("url", "")
        redirect_response = event.get("redirectResponse")

        if redirect_response:
            # This is a redirect hop on an existing request
            # fold it into the existing log entry rather than creating a new one.
            #
            # The redirectResponse field carries the status/url of the hop that just
            # completed, and request_url is the new destination
            ctx = self._request_context.get(rid)
            if ctx:
                log_entry = ctx.get("_log_entry")
                if log_entry is not None:
                    log_entry["redirect_chain"].append(
                        {
                            "url": ctx["url"],
                            "status": redirect_response.get("status"),
                        }
                    )
                    log_entry["url"] = request_url
                # Keep the same log_entry reference,
                # just update the URL so _on_response_extra attributes Set-Cookie to the right hop
                ctx["url"] = request_url
                ctx["document_url"] = document_url
            return

        raw_cookie_header = (event["request"].get("headers") or {}).get("Cookie", "")
        cookies_sent = (
            [
                part.split("=", 1)[0].strip()
                for part in raw_cookie_header.split(";")
                if part.strip()
            ]
            if raw_cookie_header
            else []
        )

        self._request_context[rid] = {
            "url": request_url,
            "document_url": document_url,
            "type": cdp_type,
            "initiator": initiator,
            "cookies_sent": cookies_sent,
        }

        easyprivacy_match = {"matched": False}
        if self.cfg.matcher and request_url and document_url:
            result = self.cfg.matcher.match(request_url, document_url, cdp_type)
            easyprivacy_match = result.to_dict()

        log_entry = {
            "url": request_url,
            "type": cdp_type,
            "status": None,
            "document_url": document_url,
            "initiator": initiator,
            "cookies_sent": cookies_sent,
            "redirect_chain": [],
            "easyprivacy": easyprivacy_match,
        }
        self._request_log.append(log_entry)
        self._request_context[rid]["_log_entry"] = log_entry

    async def _on_response_received(self, event: dict) -> None:
        rid = event["requestId"]
        status = (event.get("response") or {}).get("status")
        ctx = self._request_context.get(rid)
        if ctx and status is not None:
            log_entry = ctx.get("_log_entry")
            if log_entry is not None:
                log_entry["status"] = status

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
