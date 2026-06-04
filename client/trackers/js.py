from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import tldextract

# javascript injected before every page's own scripts
_COOKIE_GETTER_OVERRIDE_JS = """
(function () {
    // grab the original getter/setter from the prototype
    var _desc = Object.getOwnPropertyDescriptor(Document.prototype, 'cookie');
    if (!_desc || typeof _desc.get !== 'function') { return; }
    var _originalGet = _desc.get;
    var _originalSet = _desc.set;

    Object.defineProperty(document, 'cookie', {
        configurable: true,
        enumerable:   true,

        get: function () {
            var raw = _originalGet.call(this);
            try {
                if (typeof window.__reportCookieRead === 'function') {
                    var stack = '';
                    try { stack = new Error().stack || ''; } catch (e) {}
                    var frames = stack.split('\\n').slice(1, 5).join(' | ');
                    window.__reportCookieRead({
                        frameUrl:  window.location.href,
                        cookies:   raw,
                        stack:     frames,
                        ts:        Date.now(),
                    });
                }
            } catch (e) {}
            return raw;
        },

        set: function (val) {
            try {
                if (typeof window.__reportCookieWrite === 'function') {
                    var stack = '';
                    try { stack = new Error().stack || ''; } catch (e) {}
                    var frames = stack.split('\\n').slice(1, 5).join(' | ');
                    window.__reportCookieWrite({
                        frameUrl:  window.location.href,
                        rawValue:  val,
                        stack:     frames,
                        ts:        Date.now(),
                    });
                }
            } catch (e) {}
            _originalSet.call(this, val);
        },
    });
})();
"""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CookieRead:
    """One instance of document.cookie being read by JS."""

    visited_domain: str  # eTLD+1 of the top-level page being crawled
    frame_url: str  # url of the frame where the read occurred
    cookies: str  # raw document.cookie string at time of read
    stack: str  # short JS call stack
    ts: float  # unix timestamp (ms in JS, converted to s)

    def parsed_cookies(self) -> dict[str, str]:
        """Parse the raw cookie string into a {name: value} dict."""
        result = {}
        for part in self.cookies.split(";"):
            part = part.strip()
            if "=" in part:
                name, _, value = part.partition("=")
                result[name.strip()] = value.strip()
            elif part:
                result[part] = ""
        return result


@dataclass
class CookieWrite:
    """One instance of document.cookie being written by JS."""

    visited_domain: str
    frame_url: str
    raw_value: (
        str  # full string passed to the setter, e.g. "foo=bar; path=/; Max-Age=3600"
    )
    stack: str
    ts: float

    def parsed_name(self) -> str:
        """Extract the cookie name from the raw setter value."""
        first = self.raw_value.split(";", 1)[0].strip()
        return first.split("=", 1)[0].strip() if "=" in first else first


@dataclass
class InterceptorSession:
    """Accumulates CookieRead and CookieWrite events for one page visit."""

    visited_domain: str
    reads: list[CookieRead] = field(default_factory=list)
    writes: list[CookieWrite] = field(default_factory=list)

    def cookie_names_seen(self) -> set[str]:
        names: set[str] = set()
        for read in self.reads:
            names.update(read.parsed_cookies().keys())
        return names

    def to_dict(self) -> dict[str, Any]:
        # Deduplicate reads on (frame_url, cookies): keep the first occurrence of
        # each unique cookie-jar snapshot. A page may fire thousands of identical
        # read events (e.g. a consent library polling document.cookie in a tight
        # loop); only the distinct states matter for analysis.
        seen: set[tuple[str, str]] = set()
        unique_reads = []
        for r in self.reads:
            key = (r.frame_url, r.cookies)
            if key not in seen:
                seen.add(key)
                unique_reads.append(r)

        return {
            "reads": [
                {
                    "frame_url": r.frame_url,
                    "cookies": r.cookies,
                    "stack": r.stack,
                    "ts": r.ts,
                }
                for r in unique_reads
            ],
            "writes": [
                {
                    "frame_url": w.frame_url,
                    "raw_value": w.raw_value,
                    "stack": w.stack,
                    "ts": w.ts,
                }
                for w in self.writes
            ],
        }


# ---------------------------------------------------------------------------
# Interceptor class — attach to a Playwright page before goto()
# ---------------------------------------------------------------------------


class CookieReadInterceptor:
    """
    Attach to a Playwright ``page`` object to intercept all JS cookie reads.

    Usage::

        interceptor = CookieReadInterceptor(visited_domain="example.com")
        await interceptor.attach(page)          # before page.goto()
        await page.goto("https://example.com")
        await page.wait_for_timeout(5000)
        session = interceptor.session           # collect results
    """

    def __init__(self, visited_domain: str) -> None:
        self.session = InterceptorSession(visited_domain=visited_domain)
        self._lock = asyncio.Lock()
        self._is_closed: bool = False

    def close(self) -> None:
        """Signal that the page is closing; discard any future JS callbacks."""
        self._is_closed = True

    async def attach(self, page: Any) -> None:
        """
        Wire up the JS override and the Python callbacks.
        Must be called *before* page.goto().
        """
        await page.expose_function("__reportCookieRead", self._on_cookie_read)
        await page.expose_function("__reportCookieWrite", self._on_cookie_write)
        await page.add_init_script(_COOKIE_GETTER_OVERRIDE_JS)

    async def _on_cookie_read(self, event: dict[str, Any]) -> None:
        """Called from JS each time document.cookie is read."""
        if self._is_closed:
            return
        read = CookieRead(
            visited_domain=self.session.visited_domain,
            frame_url=event.get("frameUrl", ""),
            cookies=event.get("cookies", ""),
            stack=event.get("stack", ""),
            ts=event.get("ts", time.time() * 1000) / 1000.0,
        )
        async with self._lock:
            self.session.reads.append(read)

    async def _on_cookie_write(self, event: dict[str, Any]) -> None:
        """Called from JS each time document.cookie is assigned."""
        if self._is_closed:
            return
        write = CookieWrite(
            visited_domain=self.session.visited_domain,
            frame_url=event.get("frameUrl", ""),
            raw_value=event.get("rawValue", ""),
            stack=event.get("stack", ""),
            ts=event.get("ts", time.time() * 1000) / 1000.0,
        )
        async with self._lock:
            self.session.writes.append(write)


# ---------------------------------------------------------------------------
# Cross-run analysis helpers (used by find_read_trackers.py)
# ---------------------------------------------------------------------------


def build_cookie_domain_index(
    sessions: list[dict[str, Any]],
) -> dict[str, set[str]]:
    """
    Given a list of serialised InterceptorSession dicts (loaded from JSON),
    return a mapping:

        cookie_name -> {visited_domain, visited_domain, ...}

    i.e. every domain on which that cookie name was read by JS.
    """
    index: dict[str, set[str]] = defaultdict(set)

    for session in sessions:
        visited = session.get("visited_domain", "")
        for read in session.get("reads", []):
            raw = read.get("cookies", "")
            for part in raw.split(";"):
                part = part.strip()
                if not part:
                    continue
                name = part.split("=", 1)[0].strip()
                if name:
                    index[name].add(visited)

    return dict(index)


def find_cross_domain_cookies(
    index: dict[str, set[str]],
    min_domains: int = 2,
) -> list[dict[str, Any]]:
    """
    Filter the index to cookies read on at least ``min_domains`` distinct
    visited domains, sorted by domain count descending.
    """
    results = [
        {"cookie_name": name, "domain_count": len(domains), "domains": sorted(domains)}
        for name, domains in index.items()
        if len(domains) >= min_domains
    ]
    results.sort(key=lambda r: r["domain_count"], reverse=True)
    return results
