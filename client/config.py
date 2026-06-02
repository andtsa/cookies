from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional

from dotenv import load_dotenv

if TYPE_CHECKING:
    from classifier.sensitive_classifier import SensitiveClassifier

from .trackers import TrackerList
from .trackers.matcher import EasyPrivacyMatcher

load_dotenv()


class Browser(Enum):
    """Enumeration of supported browser types."""

    CHROMIUM = "chromium"
    CHROME = "chrome"
    EDGE = "edge"
    BRAVE = "brave"
    DUCKDUCKGO = "duckduckgo"
    FIREFOX = "firefox"
    WEBKIT = "webkit"


_BROWSER_CHANNEL: dict[Browser, str] = {
    Browser.CHROME: "chrome",
    Browser.EDGE: "msedge",
}

_BROWSER_ENV_KEY: dict[Browser, str] = {
    Browser.BRAVE: "BRAVE_PATH",
    Browser.DUCKDUCKGO: "DUCKDUCKGO_PATH",
}


@dataclass
class BrowserConfig:
    """per-page browser and scraping settings passed down into Client(s)"""

    browser_type: Browser = Browser.CHROMIUM
    headless: bool = True
    timeout_ms: int = 10_000
    wait_time_ms: int = 5_000
    tracker_list: Optional[TrackerList] = None
    matcher: Optional[EasyPrivacyMatcher] = None
    classifier: Optional[SensitiveClassifier] = None
    intercept_cookie_reads: bool = True


@dataclass
class CrawlConfig:
    """settings consumed by process_batch."""

    concurrency: int = 1
    start_index: int = 0
    limit: Optional[int] = None
    overwrite: bool = False
    failed_sites_path: Optional[str] = "failed_sites.csv"
    sleep_between_ms: int = 0
