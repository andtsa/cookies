
from dataclasses import dataclass, asdict
from enum import Enum
import re
from typing import List, Optional
import urllib.request

from client.trackers.abp import FilterList, parse_text
from client.trackers.ocdb import is_ocdb_tracker, parse_ocdb_list

from .util import _load_from_cache, _save_to_cache

# ("https://easylist.to/easylist/easyprivacy.txt", ListType.ABP),
# ("https://raw.githubusercontent.com/jkwakman/Open-Cookie-Database/refs/heads/master/open-cookie-database.csv", ListType.OCDB)

class Detections(Enum):
    EasyPrivacy = "https://easylist.to/easylist/easyprivacy.txt"
    OpenCookieDB = "https://raw.githubusercontent.com/jkwakman/Open-Cookie-Database/refs/heads/master/open-cookie-database.csv"

@dataclass
class TrackerDetection:
    """
    Metadata about a detected tracker.
    
    Attributes:
        lists: List of detection sources (list names/URLs)
        ocdb_match: Whether detected by Open Cookie Database
        easyprivacy_match: Whether detected by EasyPrivacy
        matched_domain: The domain from the tracker list that matched (if applicable)
    """
    lists: List[str]  # e.g., ["EasyPrivacy", "OpenCookieDB"]
    ocdb_match: bool = False
    easyprivacy_match: bool = False
    matched_domain: Optional[str] = None
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

class TrackerList:
    def __init__(self) -> None:
        self._ocdb = {}
        self._easyprivacy = FilterList()
        self.tracker_domains = set()

    def load(
        self,
        trackers: set[Detections],
        cache_dir: Optional[str] = None,
    ) -> None:
        """
        Download and parse one or more tracker lists.
        """
        for d in trackers:
            match d:
                case Detections.EasyPrivacy:
                    self._load_easyprivacy(d.value, cache_dir)
                case Detections.OpenCookieDB:
                    self._load_ocdb(d.value, cache_dir)

        print(
            f"[TrackerList] Ready: "
            f"{len(self._ocdb.keys())} cookies from OCDB, "
            f"EasyPrivacy: {self._easyprivacy.summary()}"
        )

    def is_tracker(self, cookie: dict) -> Optional[TrackerDetection]:
        """
        Check if the cookie is identified as a tracker and return detection metadata.
        
        Returns:
            TrackerDetection object with metadata if cookie is identified as a tracker,
            None otherwise.
        """
        detections = []
        ocdb_match = False
        easyprivacy_match = False
        matched_domain = None

        ocdb_match = self._is_ocdb_tracker(cookie)
        if ocdb_match:
            detections.append("OpenCookieDB")

        matched_domain, easyprivacy_match = self._is_ep_tracker(cookie)
        if easyprivacy_match:
            detections.append("EasyPrivacy")

        if not detections:
            return None

        return TrackerDetection(
            lists=detections,
            ocdb_match=ocdb_match,
            easyprivacy_match=easyprivacy_match,
            matched_domain=matched_domain,
        )

    def _fetch(self, url: str, cache_dir: Optional[str]) -> str:
        if cache_dir:
            cached = _load_from_cache(url, cache_dir)
            if cached is not None:
                return cached

        print(f"[TrackerList] Downloading {url} …")
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (cookie-research-bot/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8", errors="ignore")

        if cache_dir:
            _save_to_cache(url, cache_dir, text)

        return text

    def _load_easyprivacy(self, url: str, cache_dir: Optional[str]):
        text = self._fetch(url, cache_dir)
        self._easyprivacy = parse_text(text)
        print(f"[TrackerList] loaded EasyPrivacy:\n{self._easyprivacy.summary()}")
        for rule in self._easyprivacy.block_rules:
            if rule.is_domain_anchor and not rule.options.domain_includes:
                # Strip || and ^ to get the bare domain
                domain = rule.pattern.lstrip("|").rstrip("^").lstrip("/")
                # Keep only clean hostnames (no wildcards, no paths)
                if re.match(r'^[\w.-]+$', domain):
                    self.tracker_domains.add(domain)
        print(f"[TrackerList] loaded {len(self.tracker_domains)} EasyPrivacy tracker domains")
        
    def _load_ocdb(self, url: str, cache_dir: Optional[str]):
        text = self._fetch(url, cache_dir)
        self._ocdb = parse_ocdb_list(text)
        print(f"[TrackerList] loaded {len(self._ocdb)} ocdb rules")

    def _is_ocdb_tracker(self, cookie: dict) -> bool:
        if self._ocdb is None:
            return False
        return is_ocdb_tracker(cookie, self._ocdb)

    def _is_ep_tracker(self, cookie: dict) -> tuple[Optional[str], bool]:
        """
        Check if cookie domain matches EasyPrivacy tracker domains.
        
        Returns:
            Tuple of (matched_domain, is_match) where matched_domain is the
            domain from tracker_domains that matched, or None if no match.
        """
        if len(self.tracker_domains) == 0:
            return None, False
        # Normalise: strip leading dot
        d = cookie["domain"].lstrip(".")
        # Check exact match and parent domains
        parts = d.split(".")
        for i in range(len(parts) - 1):
            candidate = ".".join(parts[i:])
            if candidate in self.tracker_domains:
                return candidate, True
        return None, False
        

