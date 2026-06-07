"""
Cookie-syncing detection, from scripts/find_cookie_syncing.py

Detects a cookie value (or a known encoding of it) being passed as a query
parameter to a *different* registered domain (direct evidence an identifier
crossed a domain boundary). Unlike the original script this only *returns*
results; it never annotates the source JSON.
"""

from __future__ import annotations

import base64
from urllib.parse import parse_qsl, quote, unquote, urlparse

from client.trackers.entropy import total_bits

from .helpers import HIGH_ENTROPY_BITS, registered_domain

# Minimum cookie-value length to consider for exact matching. Very short values
# ("1", "true", "en") produce noisy substring hits and are not UIDs.
MIN_PRIMARY_VALUE_LEN = 8
# Deep-match substring guards: only embed-match long, high-entropy values so a
# common token does not produce spurious hits inside a larger param.
DEEP_SUBSTRING_MIN_LEN = 16
DEEP_SUBSTRING_MIN_BITS = 60.0


def _param_values(url: str) -> list[tuple[str, str]]:
    query = urlparse(url).query
    if not query:
        return []
    return parse_qsl(query, keep_blank_values=False)


def _b64_variants(s: str) -> set[str]:
    out: set[str] = set()
    try:
        out.add(base64.b64encode(s.encode()).decode())
    except Exception:
        pass
    try:
        out.add(base64.urlsafe_b64encode(s.encode()).decode().rstrip("="))
    except Exception:
        pass
    for pad in ("", "=", "=="):
        for dec in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                decoded = dec(s + pad).decode("latin-1")
                if len(decoded) >= MIN_PRIMARY_VALUE_LEN:
                    out.add(decoded)
            except Exception:
                pass
    return {f for f in out if len(f) >= MIN_PRIMARY_VALUE_LEN}


def _norm_forms(s: str, deep: bool) -> set[str]:
    forms = {s, unquote(s), quote(s, safe="")}
    if deep:
        for base in (s, unquote(s)):
            forms |= _b64_variants(base)
    return {f for f in forms if len(f) >= MIN_PRIMARY_VALUE_LEN}


def analyze_site(
    data: dict, min_bits: float = HIGH_ENTROPY_BITS, deep: bool = False
) -> dict:
    """Detect sync events for one loaded site JSON.

    Returns ``{"site_domain", "confirmed": [...], "candidates": [...]}`` exactly
    as scripts/find_cookie_syncing.py produced, so existing reporting is reusable.
    """
    target_url = data.get("target_url", "")
    site_domain = registered_domain(target_url)
    requests = data.get("requests", []) or []
    cookies = data.get("cookies", []) or []

    exact_index: dict[str, str] = {}
    embeddable: list[tuple[str, str]] = []
    for c in cookies:
        value = c.get("value", "") or ""
        if len(value) < MIN_PRIMARY_VALUE_LEN:
            continue
        name = c.get("name", "")
        for form in _norm_forms(value, deep):
            exact_index.setdefault(form, name)
        if (
            deep
            and len(value) >= DEEP_SUBSTRING_MIN_LEN
            and total_bits(value) >= DEEP_SUBSTRING_MIN_BITS
        ):
            embeddable.append((value, name))

    confirmed: list[dict] = []
    candidates: list[dict] = []

    for req in requests:
        url = req.get("url", "")
        if not url:
            continue
        to_domain = registered_domain(url)
        if not to_domain or to_domain == site_domain:
            continue

        for param_name, raw_value in _param_values(url):
            if not raw_value:
                continue
            decoded = unquote(raw_value)

            matched_name = None
            match_kind = "exact"
            for form in _norm_forms(raw_value, deep):
                if form in exact_index:
                    matched_name = exact_index[form]
                    break

            if matched_name is None and deep:
                for value, name in embeddable:
                    if value in decoded or value in raw_value:
                        matched_name = name
                        match_kind = "substring"
                        break

            if matched_name is not None:
                confirmed.append(
                    {
                        "cookie_name": matched_name,
                        "param": param_name,
                        "to_domain": to_domain,
                        "request_url": url,
                        "match": match_kind,
                    }
                )
                continue

            if (
                len(decoded) >= MIN_PRIMARY_VALUE_LEN
                and total_bits(decoded) >= min_bits
            ):
                candidates.append(
                    {
                        "param": param_name,
                        "value_preview": decoded[:12]
                        + ("…" if len(decoded) > 12 else ""),
                        "total_bits": round(total_bits(decoded), 1),
                        "to_domain": to_domain,
                        "request_url": url,
                    }
                )

    return {
        "site_domain": site_domain,
        "confirmed": confirmed,
        "candidates": candidates,
    }
