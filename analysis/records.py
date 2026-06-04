"""
analysis/records.py
-------------------
Lightweight, frozen record types.

The enriched pandas frames in :mod:`analysis.dataset` are the single source of
truth; these dataclasses are *projections* for callers that prefer objects over
DataFrame rows. ``CookieRecord`` keeps a ``raw`` back-pointer to the original
cookie dict as an escape hatch for fields not promoted to a column.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SiteRaw:
    """One crawled site JSON plus the context decoded from its path."""

    path: Path
    country: str
    browser: str
    domain: str  # filename slug, e.g. "pinterest_com"
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


@dataclass(frozen=True)
class CookieRecord:
    """A single enriched cookie, projected from a row of ``dataset.cookies``."""

    country: str
    browser: str
    category: str
    registered_domain: str
    name: str
    name_family: str
    value: str
    md5_value: str
    cookie_type: str
    party_type: str
    is_tracker: bool
    tracker_provider: str | None
    total_bits: float
    lifetime_days: float | None
    lifetime_bucket: str
    setter_domain: str | None
    raw: dict = field(default_factory=dict, repr=False)
