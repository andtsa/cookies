import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from .client import Client
from .trackers import TrackerList


class ChromiumClient(Client):
    """
    Concrete implementation of Client interface using Chromium via Playwright.

    Uses Chrome DevTools Protocol (CDP) for advanced automation features
    like cookie management and network monitoring.
    """

    def __init__(self, tracker_list: Optional[TrackerList] = None):
        self.playwright = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.client = None
        # tracker list for annotating cookies with `is_tracker`
        # if None, is_tracker will not be included in the output JSON
        self.tracker_list = tracker_list

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
        self.browser = await self.playwright.chromium.launch(headless=headless)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        self.client = await self.context.new_cdp_session(self.page)

        # Enable required CDP domains
        await self.client.send("Page.enable")
        await self.client.send("Network.enable")
        await self.client.send("Network.clearBrowserCookies")

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

        now = datetime.now(timezone.utc)
        now_ts = now.timestamp()

        cookies_metadata = []

        num_session = 0
        num_persistent = 0
        num_trackers = 0
        lifetime_values = []

        for cookie in cookies:
            is_session = cookie.get("session", False)
            expires = cookie.get("expires", -1)
            cookie_domain = cookie.get("domain", "")
            cookie_name = cookie.get("name", "")

            # Session cookies do not persist after session close
            if is_session or expires == -1:
                num_session += 1
                cookie_type = "session"
                expiration_datetime = None
                lifetime_seconds = None
                lifetime_days = None

            else:
                num_persistent += 1
                cookie_type = "persistent"

                expiration_datetime = datetime.fromtimestamp(
                    expires, tz=timezone.utc
                ).isoformat()

                lifetime_seconds = expires - now_ts
                lifetime_days = lifetime_seconds / 86400

                if lifetime_days >= 0:
                    lifetime_values.append(lifetime_days)

            # check domain & name against the loaded filter lists
            # if no tracker_list was provided, omit the field entirely
            # so existing consumers don't break
            tracker_detection = None
            if self.tracker_list is not None:
                tracker_detection = self.tracker_list.is_tracker(cookie)
                if tracker_detection:
                    num_trackers += 1

            # build per-cookie record
            single_cookie_metadata = {
                "name": cookie_name,
                "domain": cookie_domain,
                "session": is_session,
                "cookie_type": cookie_type,
                "secure": cookie.get("secure"),
                "httpOnly": cookie.get("httpOnly"),
                "sameSite": cookie.get("sameSite"),
                "expires_unix": expires,
                "expiration_datetime": expiration_datetime,
                "lifetime_seconds": lifetime_seconds,
                "lifetime_days": lifetime_days,
            }

            if tracker_detection is not None:
                single_cookie_metadata["is_tracker"] = tracker_detection.to_dict()
            else:
                single_cookie_metadata["is_tracker"] = False

            cookies_metadata.append(single_cookie_metadata)

        avg_lifetime_days = (
            sum(lifetime_values) / len(lifetime_values) if lifetime_values else None
        )

        max_lifetime_days = max(lifetime_values) if lifetime_values else None

        min_lifetime_days = min(lifetime_values) if lifetime_values else None

        site_metadata = {
            "collection_timestamp": now.isoformat(),
            "wait_time_seconds": params.get("wait_time_seconds"),
            "total_cookies": len(cookies_metadata),
            "num_session": num_session,
            "num_persistent": num_persistent,
            "avg_lifetime_days": avg_lifetime_days,
            "min_lifetime_days": min_lifetime_days,
            "max_lifetime_days": max_lifetime_days,
        }

        # include tracker summary stats only when a TrackerList was provided.
        if self.tracker_list is not None:
            site_metadata["num_trackers"] = num_trackers
            site_metadata["pct_trackers"] = (
                round(num_trackers / len(cookies_metadata) * 100, 1)
                if cookies_metadata
                else 0.0
            )

        output_data = {
            "target_url": params.get("target_url"),
            "site_metadata": site_metadata,
            "cookies": cookies_metadata,
        }

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, output_name)
        else:
            output_path = output_name

        with open(output_path, "w", encoding="utf-8") as f:
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
