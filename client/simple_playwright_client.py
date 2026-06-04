import tldextract
from playwright.async_api import async_playwright

from .client import Client
from .config import BrowserConfig, Site
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

    async def _on_close_get_cookies_snapshot(self, output: Outfile, site: Site) -> None:
        assert self.context is not None, "Context not initialized"
        assert (
            self.browser is not None and self.playwright is not None
        ), "Not initialized"

        cookies = await self.context.cookies()

        if self.cfg.classifier:
            sensitivity_result = self.cfg.classifier.classify_html(
                await self.page.content()
            )
        else:
            sensitivity_result = None

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
        redirected_from = request.redirected_from

        if redirected_from is not None:
            # This request is the destination of a redirect.  Playwright fires
            # _on_response for the redirecting request before firing _on_request
            # for the destination, so the originating log entry already has its
            # status code patched in.  Fold this hop into that entry.
            origin_ctx = self._request_context.get(redirected_from.url)
            if origin_ctx:
                log_entry = origin_ctx["_log_entry"]
                log_entry["redirect_chain"].append(
                    {
                        "url": redirected_from.url,
                        "status": log_entry["status"],
                    }
                )
                log_entry["url"] = request_url
                log_entry["status"] = None  # will be patched by _on_response
                # re-key the context entry so _on_response can find it
                self._request_context[request_url] = origin_ctx
                return

        easyprivacy_match = {"matched": False}
        if self.cfg.matcher and request_url and document_url:
            result = self.cfg.matcher.match(request_url, document_url, resource_type)
            easyprivacy_match = result.to_dict()

        log_entry = {
            "url": request_url,
            "type": resource_type,
            "status": None,
            "document_url": document_url,
            "initiator": "",  # not available via Playwright standard API
            "cookies_sent": [],  # Cookie header not exposed via Playwright standard API
            "redirect_chain": [],
            "easyprivacy": easyprivacy_match,
        }
        self._request_log.append(log_entry)
        # keep a reference keyed by URL so _on_response can patch in the status
        self._request_context[request_url] = {"_log_entry": log_entry}

    async def _on_response(self, response) -> None:
        if self._is_closed:
            return
        try:
            headers = await response.all_headers()
        except Exception:
            return

        # patch status back onto the matching request log entry
        log_entry = (self._request_context.get(response.request.url) or {}).get(
            "_log_entry"
        )
        if log_entry is not None:
            log_entry["status"] = response.status

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
