from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional

from dotenv import load_dotenv

if TYPE_CHECKING:
    from classifier.sensitive_classifier import SensitiveClassifier

from .trackers import TrackerList

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

_BROWSER_USER_AGENTS: dict[Browser, str] = {
    Browser.CHROMIUM: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
                      
    Browser.CHROME: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
                    
    Browser.EDGE: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0",
                  
    Browser.BRAVE: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
                   
    Browser.FIREFOX: "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
                     "Gecko/20100101 Firefox/133.0",
                     
    Browser.WEBKIT: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
                    
    Browser.DUCKDUCKGO: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
}


@dataclass
class BrowserConfig:
    """per-page browser and scraping settings passed down into Client(s)"""

    browser_type: Browser = Browser.CHROMIUM
    headless: bool = True
    timeout_ms: int = 10_000
    wait_time_ms: int = 5_000
    tracker_list: Optional[TrackerList] = None
    classifier: Optional[SensitiveClassifier] = None
    intercept_cookie_reads: bool = True
    user_agent: Optional[str] = None


@dataclass
class CrawlConfig:
    """settings consumed by process_batch."""

    concurrency: int = 1
    start_index: int = 0
    limit: Optional[int] = None
    overwrite: bool = False
    failed_sites_path: Optional[str] = "failed_sites.csv"
    sleep_between_ms: int = 0
    output_dir: str = "cookies_data/Netherlands"
    country: str = "unknown"


@dataclass
class Site:
    url: str
    rank: int
    category: str | None
