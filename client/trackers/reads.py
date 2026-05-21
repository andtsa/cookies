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
    // grab the original getter from the prototype so we always call the real one
    var _desc = Object.getOwnPropertyDescriptor(Document.prototype, 'cookie');
    if (!_desc || typeof _desc.get !== 'function') { return; }
    var _originalGet = _desc.get;

    Object.defineProperty(document, 'cookie', {
        configurable: true,
        enumerable:   true,

        get: function () {
            var raw = _originalGet.call(this);
            try {
                // __reportCookieRead is registered by playwright's exposeFunction
                // before this script runs, so it should always be present
                if (typeof window.__reportCookieRead === 'function') {
                    // collect a shallow stack trace (and skip this wrapper frame)
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
            } catch (e) {
                // never let instrumentation break the page
            }
            return raw;
        },

        // preserve the original setter so writes still work normally
        set: _desc.set,
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
class InterceptorSession:
    """Accumulates CookieRead events for one page visit."""

    visited_domain: str
    reads: list[CookieRead] = field(default_factory=list)

    def cookie_names_seen(self) -> set[str]:
        names: set[str] = set()
        for read in self.reads:
            names.update(read.parsed_cookies().keys())
        return names

    def to_dict(self) -> dict[str, Any]:
        return {
            "visited_domain": self.visited_domain,
            "reads": [
                {
                    "frame_url": r.frame_url,
                    "cookies": r.cookies,
                    "stack": r.stack,
                    "ts": r.ts,
                }
                for r in self.reads
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

    async def attach(self, page: Any) -> None:
        """
        Wire up the JS override and the Python callback.
        Must be called *before* page.goto().
        """
        # 1. Register the Python-side callback so JS can call it.
        #    Playwright serialises the JS argument dict → Python dict automatically.
        await page.expose_function("__reportCookieRead", self._on_cookie_read)

        # 2. Inject the getter override into every (same-origin) frame.
        await page.add_init_script(_COOKIE_GETTER_OVERRIDE_JS)

    async def _on_cookie_read(self, event: dict[str, Any]) -> None:
        """Called from JS each time document.cookie is read."""
        read = CookieRead(
            visited_domain=self.session.visited_domain,
            frame_url=event.get("frameUrl", ""),
            cookies=event.get("cookies", ""),
            stack=event.get("stack", ""),
            ts=event.get("ts", time.time() * 1000) / 1000.0,
        )
        async with self._lock:
            self.session.reads.append(read)


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
