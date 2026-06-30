"""Detect cookie syncing: cookie-value identifiers embedded in outgoing request URLs."""

from __future__ import annotations

import base64
import re
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

# Glob-style endpoint patterns for URL-path / param-name based syncing.
# '*' = any run of token chars, '?' = one token char; plain words are exact
# tokens. Entries may include globs, e.g. "sync*". Ordered longest-first so the
# alternation prefers the most specific match ("usersync" before "sync").
SYNC_ENDPOINT_PATTERNS = (
    "usermatchredir",
    "cookie-sync",
    "cookie_sync",
    "partner_uid",
    "usersync",
    "redirect",
    "ttd_id",
    "partner",
    "track",
    "sync",
    "match",
    "*sync*",
    "*cookie*",
)


def _glob_to_regex(pat: str) -> str:
    """Translate a glob ('*','?') to a token-scoped regex fragment.

    '*' -> any run of token chars, '?' -> one token char; every other char is
    escaped literally. Token chars are ``[a-z0-9_-]``, so a glob never crosses a
    path/query delimiter (``/``, ``?``, ``=``, ``&``).
    """
    out = []
    for ch in pat.lower():
        if ch == "*":
            out.append(r"[a-z0-9_-]*")
        elif ch == "?":
            out.append(r"[a-z0-9_-]")
        else:
            out.append(re.escape(ch))
    return "".join(out)


class PathSyncDetector:
    """Detect sync-endpoint keywords in a request's URL path and param names.

    Token-boundary matching: a pattern matches only when it is not flanked by an
    alphanumeric character, so "track" does not fire inside "attachment" and
    "cookie-sync" matches as a single unit. Patterns are glob-style (see
    :func:`_glob_to_regex`). Build once, reuse across requests — the alternation
    regex is precompiled.
    """

    def __init__(self, patterns: tuple[str, ...] | None = None) -> None:
        pats = tuple(patterns) if patterns else SYNC_ENDPOINT_PATTERNS
        # Longest-first so the alternation prefers the most specific pattern.
        ordered = sorted({p.lower() for p in pats}, key=len, reverse=True)
        alt = "|".join(_glob_to_regex(p) for p in ordered)
        # (?<![a-z0-9]) ... (?![a-z0-9]) gives the token/segment boundary.
        self._pattern = re.compile(rf"(?<![a-z0-9])({alt})(?![a-z0-9])")

    def _keywords_in(self, text: str) -> list[str]:
        # Returns the actual matched substrings (e.g. "syncing" for glob "sync*").
        return self._pattern.findall(text.lower()) if text else []

    def match(self, url: str, to_domain: str) -> dict | None:
        """Return endpoint-keyword evidence for one URL, or ``None`` if no hit.

        Looks in the URL path and in each query-parameter *name* (not value).
        """
        parsed = urlparse(url)
        path_kw = self._keywords_in(parsed.path)
        name_kw: list[str] = []
        for name, _val in parse_qsl(parsed.query, keep_blank_values=False):
            name_kw.extend(self._keywords_in(name))
        if not path_kw and not name_kw:
            return None
        where = "both" if path_kw and name_kw else ("path" if path_kw else "param")
        return {
            "to_domain": to_domain,
            "request_url": url,
            "path_keywords": sorted(set(path_kw)),
            "param_keywords": sorted(set(name_kw)),
            "where": where,
        }


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
    data: dict,
    min_bits: float = HIGH_ENTROPY_BITS,
    deep: bool = False,
    path_detector: "PathSyncDetector | None" = None,
) -> dict:
    """Detect sync events for one loaded site JSON.

    When ``path_detector`` is provided, the PATH layer annotates any confirmed or
    candidate row whose cross-domain request also hit a known sync-endpoint
    keyword (in the URL path or a query-parameter name) with a ``path_sync``
    field ``{path_keywords, param_keywords, where, kind}``. ``kind`` is
    ``"cookie"`` for confirmed rows (the overlap with value-matching) and
    ``"entropy"`` for candidate rows (exclusive to the path heuristic).

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

        # Rows produced by *this* request, so the PATH layer can annotate them.
        req_confirmed: list[dict] = []
        req_candidates: list[dict] = []

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
                req_confirmed.append(
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
                req_candidates.append(
                    {
                        "param": param_name,
                        "value_preview": decoded[:12]
                        + ("…" if len(decoded) > 12 else ""),
                        "total_bits": round(total_bits(decoded), 1),
                        "to_domain": to_domain,
                        "request_url": url,
                    }
                )

        # PATH: if this cross-domain request hits a known sync endpoint, attach
        # the endpoint evidence to every identifier row it produced. The rows
        # *are* the corroborating identifier (a confirmed cookie or a candidate).
        if path_detector is not None and (req_confirmed or req_candidates):
            ev = path_detector.match(url, to_domain)
            if ev is not None:
                base = {
                    "path_keywords": ev["path_keywords"],
                    "param_keywords": ev["param_keywords"],
                    "where": ev["where"],
                }
                for row in req_confirmed:
                    row["path_sync"] = {**base, "kind": "cookie"}
                for row in req_candidates:
                    row["path_sync"] = {**base, "kind": "entropy"}

        confirmed.extend(req_confirmed)
        candidates.extend(req_candidates)

    return {
        "site_domain": site_domain,
        "confirmed": confirmed,
        "candidates": candidates,
    }


# ---------------------------------------------------------------------------
# Subtype derivation (per-param-row dimensions for the sync plots)
# ---------------------------------------------------------------------------

# Map a Chromium resource ``type`` to the carrier (mechanism) the identifier
# rode on. A derivable proxy for the academic initiator taxonomy.
_CARRIER_BY_TYPE = {
    "Image": "pixel",
    "Ping": "beacon",
    "Script": "script",
    "XHR": "xhr/fetch",
    "Fetch": "xhr/fetch",
    "Document": "redirect/navigation",
    "Prefetch": "redirect/navigation",
}


def carrier_of(req_type: str) -> str:
    """Carrier subtype for a Chromium request resource ``type``."""
    return _CARRIER_BY_TYPE.get(req_type or "", "other")


def encoding_of(raw_value: str, cookie_value: str, match_kind: str) -> str:
    """Classify how a confirmed sync's param ``raw_value`` encodes the cookie.

    ``raw`` (verbatim) / ``url-encoded`` (percent-encoded) / ``base64`` /
    ``substring`` (embedded, deep mode). Falls back to ``raw`` when the cookie
    value is unavailable, since the detector already proved a match.
    """
    if match_kind == "substring":
        return "substring"
    if not cookie_value:
        return "raw"
    if raw_value == cookie_value:
        return "raw"
    decoded = unquote(raw_value)
    if decoded == cookie_value:
        return "url-encoded"
    if raw_value in _b64_variants(cookie_value) or decoded in _b64_variants(
        cookie_value
    ):
        return "base64"
    if cookie_value in _b64_variants(decoded):
        return "base64"
    return "raw"


def param_value_in(url: str, param: str) -> str:
    """Return the raw (still-encoded) value of ``param`` in ``url``'s query."""
    for name, val in parse_qsl(urlparse(url).query, keep_blank_values=False):
        if name == param:
            return val
    return ""
