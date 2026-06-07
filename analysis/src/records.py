from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SiteRaw:
    """One crawled site JSON plus the context decoded from its path"""

    path: Path
    country: str
    browser: str
    domain: str
    data: dict

    @property
    def target_url(self) -> str:
        return self.data.get("target_url", "")

    @property
    def cookies(self) -> list[dict]:
        return self.data.get("cookies", []) or []

    @property
    def requests(self) -> list[dict]:
        return self.data.get("requests", []) or []

    @property
    def js_activity(self) -> dict:
        return self.data.get("js_activity", {}) or {}
