"""Extract third-party cookie reads from recorded JavaScript stack traces."""

from __future__ import annotations

import re

from .helpers import registered_domain

# First http(s) URL in a JS call-stack frame string. The earliest frame is the
# script that actually triggered the document.cookie read.
_URL_RE = re.compile(r"https?://[^\s)]+")


def extract_primary_reader(stack: str) -> tuple[str | None, str | None]:
    """Return ``(reader_domain, reader_script_url)`` from a JS stack trace.

    The reader is the first script URL in the stack; ``reader_domain`` is its
    registered domain. ``(None, None)`` when the stack has no URL (e.g. an
    inline first-party script).
    """
    urls = _URL_RE.findall(stack or "")
    if not urls:
        return None, None
    script_url = urls[0]
    return registered_domain(script_url) or None, script_url


def third_party_reads(sessions: list[dict]) -> list[dict]:
    """Flatten cross-party cookie reads from a list of read sessions.

    Each ``session`` is ``{"visited_domain", "reads": [{"cookies", "stack"}]}``.
    Returns one record per (cookie_name, visited_domain, reader_domain,
    reader_script) — deduplicated, first-party readers dropped — shaped like the
    old ``reads_filtered.json`` rows but expanded to one row per cookie name::

        {cookie_name, visited_domain, reader_domain, reader_script}
    """
    seen: set[tuple] = set()
    out: list[dict] = []
    for session in sessions:
        visited = session.get("visited_domain", "")
        for read in session.get("reads", []):
            reader_domain, reader_script = extract_primary_reader(read.get("stack", ""))
            # Unknown reader, or a first-party read -> not a cross-party signal.
            if not reader_domain or reader_domain == visited:
                continue
            for part in (read.get("cookies", "") or "").split(";"):
                part = part.strip()
                if not part:
                    continue
                cookie_name = part.split("=", 1)[0].strip()
                if not cookie_name:
                    continue
                key = (cookie_name, visited, reader_domain, reader_script)
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "cookie_name": cookie_name,
                        "visited_domain": visited,
                        "reader_domain": reader_domain,
                        "reader_script": reader_script,
                    }
                )
    return out
