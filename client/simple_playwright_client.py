import tldextract
from playwright.async_api import async_playwright

from .client import Client
from .config import BrowserConfig
from .output import Outfile, OutputFormat
from .util import _parse_set_cookie_name


class SimplePlaywrightClient(Client):
    """
    Playwright client for non-Chromium engines (Firefox, WebKit).
    """

    def __init__(self, cfg: BrowserConfig):
        super().__init__(cfg)

    # engine-specific hooks

    async def _setup(self, url: str) -> None:
        self.playwright = await async_playwright().start()
        launcher = getattr(self.playwright, self.cfg.browser_type.value)
        self.browser = await launcher.launch(headless=self.cfg.headless)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        await self.context.clear_cookies()

        self.page.on("request", self._on_request)
        self.page.on("response", self._on_response)

        await self._attach_cookie_read_interceptor(url)

    async def _navigate_to_page(self, url: str) -> None:
        assert self.page is not None, "Page not initialized"
        await self.page.goto(url, wait_until="load", timeout=self.cfg.timeout_ms)

    async def _on_close_get_cookies_snapshot(self, output: Outfile) -> None:
        assert self.context is not None, "Context not initialized"
        assert (
            self.browser is not None and self.playwright is not None
        ), "Not initialized"

        self.page_html = await self.page.content()
        cookies = await self.context.cookies()

        sensitivity_result = (
            self.cfg.classifier.classify_html(self.page_html)
            if self.cfg.classifier
            else None
        )

        OutputFormat.process_and_save(
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

    # playwright event handlers

    def _on_request(self, request) -> None:
        request_url = request.url
        document_url = request.frame.url if request.frame else ""
        resource_type = request.resource_type

        easyprivacy_match = {"matched": False}
        if self.cfg.matcher and request_url and document_url:
            result = self.cfg.matcher.match(request_url, document_url, resource_type)
            easyprivacy_match = result.to_dict()

        self._request_log.append(
            {
                "url": request_url,
                "type": resource_type,
                "easyprivacy": easyprivacy_match,
            }
        )

    async def _on_response(self, response) -> None:
        if self._is_closed:
            return
        try:
            headers = await response.all_headers()
        except Exception:
            return

        set_cookie = headers.get("set-cookie", "")
        if not set_cookie:
            return

        request = response.request
        request_url = request.url
        document_url = request.frame.url if request.frame else ""
        resource_type = request.resource_type

        request_domain = tldextract.extract(request_url).registered_domain
        page_domain = tldextract.extract(document_url).registered_domain

        if not request_domain or not page_domain:
            return

        for raw_cookie in set_cookie.split("\n"):
            name = _parse_set_cookie_name(raw_cookie)
            if not name:
                continue
            key = (name, request_domain)
            self._cookie_set_context[key] = {
                "set_by_request_url": request_url,
                "set_by_request_type": resource_type,
                "set_by_initiator": "",  # not available via Playwright standard API
                "is_third_party_set": request_domain != page_domain,
            }
