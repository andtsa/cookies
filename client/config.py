from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .trackers import TrackerList
from .trackers.matcher import EasyPrivacyMatcher


@dataclass
class BrowserConfig:
    """per-page browser and scraping settings passed down into Client(s)"""

    headless: bool = True
    timeout_ms: int = 10_000
    wait_time_ms: int = 5_000
    tracker_list: Optional[TrackerList] = None
    matcher: Optional[EasyPrivacyMatcher] = None
    intercept_cookie_reads: bool = True


@dataclass
class CrawlConfig:
    """settings consumed by process_batch."""

    concurrency: int = 1
    limit: Optional[int] = None
    overwrite: bool = False
    failed_sites_path: Optional[str] = None
    sleep_between_ms: int = 0
