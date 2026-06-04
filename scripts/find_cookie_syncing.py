"""
scripts/find_cookie_syncing.py
------------------------------
Detect *cookie syncing* — trackers sharing a user identifier with one another by
passing a cookie's value to a different domain through request parameters.

This is post-hoc analysis over the ``requests`` field that get_cookies.py now
stores for Chromium-family crawls (full request URLs with query strings), plus
the ``cookies`` already in each site JSON.

Three layers of evidence (per the agreed design):

  PRIMARY (strong)
      A cookie value observed on the site (and its URL-encoded form) appears as
      a query-parameter value in a request sent to a *different registered
      domain*. This is direct proof the identifier crossed a domain boundary.

  SECONDARY (candidate)
      A query-parameter value sent cross-domain is high-entropy and long enough
      to look like a UID, even though we did not match it to a known cookie.
      Reported separately as a weaker "candidate" signal.

  PATH (endpoint heuristic)
      A cross-domain request hits a known sync-endpoint keyword in its URL path
      or a query-parameter *name* (e.g. /usersync, /cookie-sync, partner_uid).
      This is not a separate population: it *annotates* the confirmed/candidate
      rows the request already produced with a ``path_sync`` field (those rows
      are the corroborating identifier). See ``PathSyncDetector``.

For each site this writes a ``cookie_syncing`` field back into the JSON (like
process_cookies.py adds party_type) and prints a cross-site aggregate report of
which domain pairs sync identifiers.

Usage
-----
    python scripts/find_cookie_syncing.py cookies_data/chromium
    python scripts/find_cookie_syncing.py cookies_data --min-bits 36
    python scripts/find_cookie_syncing.py cookies_data --no-annotate --out syncs.json
    python scripts/find_cookie_syncing.py cookies_data --deep-match   # base64 + embedded
    python scripts/find_cookie_syncing.py cookies_data --no-path-match # skip endpoint heuristic
"""

from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import re
import sys
from collections import Counter
from urllib.parse import parse_qsl, quote, unquote, urlparse

import tldextract

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from client.trackers.entropy import total_bits

# Minimum cookie-value length to consider for PRIMARY matching. Very short
# values ("1", "true", "en") produce noisy substring hits and are not UIDs.
MIN_PRIMARY_VALUE_LEN = 8
# Default total_bits cutoff for SECONDARY (candidate) high-entropy params.
DEFAULT_MIN_BITS = 36.0
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
    "*cookie*"
    # globs are supported, e.g. add "sync*" / "*match*" here.
)


def _registered_domain(url_or_host: str) -> str:
    return tldextract.extract(url_or_host).registered_domain or url_or_host


def _param_values(url: str) -> list[tuple[str, str]]:
    """Return (param_name, param_value) pairs from a URL's query string.

    Values are URL-decoded so they can be compared against raw cookie values.
    """
    query = urlparse(url).query
    if not query:
        return []
    return parse_qsl(query, keep_blank_values=False)


def _b64_variants(s: str) -> set[str]:
    """Base64 encodings and decodings of ``s`` (best-effort, never raises).

    Returns both the base64-*encoded* forms of ``s`` (so a cookie value sent in
    encoded form is found) and the base64-*decoded* forms (so a param that is a
    base64 of the value is found). Only forms of a useful length are kept.
    """
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
    """All representations of ``s`` we treat as equal for exact matching.

    Always includes the raw value, its URL-decoded form and its URL-encoded
    form (so raw/percent-encoded params match in either direction). With
    ``deep``, also includes base64 encodings/decodings. Computed on both the
    cookie and the param side, so an identifier encoded differently on each end
    still matches when the two form-sets intersect.
    """
    forms = {s, unquote(s), quote(s, safe="")}
    if deep:
        for base in (s, unquote(s)):
            forms |= _b64_variants(base)
    return {f for f in forms if len(f) >= MIN_PRIMARY_VALUE_LEN}


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


def analyze_site(
    data: dict,
    min_bits: float,
    deep: bool = False,
    path_detector: "PathSyncDetector | None" = None,
) -> dict:
    """Detect sync events for one loaded site JSON.

    With ``deep`` the PRIMARY matcher also recognises base64-encoded forms of a
    cookie value, and embedded (substring) occurrences of long, high-entropy
    values. This catches more transformed syncs at the cost of some false-
    positive risk, so it is opt-in.

    When ``path_detector`` is provided, the PATH layer annotates any confirmed
    or candidate row whose cross-domain request also hit a known sync-endpoint
    keyword (in the URL path or a query-parameter name) with a ``path_sync``
    field. The annotated row *is* the corroborating identifier, so ``kind``
    records which: "cookie" rows overlap with the confirmed layer; "entropy"
    rows are exclusive to the path heuristic.

    Returns a ``cookie_syncing`` dict:
        {
          "site_domain": <registered domain of the page>,
          "confirmed": [ {cookie_name, param, to_domain, request_url, match,
                          path_sync?}, ...],
          "candidates": [ {param, value_preview, total_bits, to_domain,
                          request_url, path_sync?}, ...],
        }
    where ``path_sync`` (optional) is
        {path_keywords, param_keywords, where, kind}.
    """
    target_url = data.get("target_url", "")
    site_domain = _registered_domain(target_url)
    requests = data.get("requests", [])
    cookies = data.get("cookies", [])

    # Exact-form index: every normalised representation of a cookie value -> name.
    exact_index: dict[str, str] = {}
    # Long, high-entropy values eligible for substring (embedded) matching.
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

    confirmed = []
    candidates = []

    for req in requests:
        url = req.get("url", "")
        if not url:
            continue
        to_domain = _registered_domain(url)
        # Only cross-domain requests can be syncs.
        if not to_domain or to_domain == site_domain:
            continue

        # Rows produced by *this* request, so the PATH layer can annotate them.
        req_confirmed = []
        req_candidates = []

        for param_name, raw_value in _param_values(url):
            if not raw_value:
                continue
            decoded = unquote(raw_value)

            # PRIMARY (exact): a normalised form of the param equals a cookie's.
            matched_name = None
            match_kind = "exact"
            for form in _norm_forms(raw_value, deep):
                if form in exact_index:
                    matched_name = exact_index[form]
                    break

            # PRIMARY (embedded): a long high-entropy cookie value appears inside
            # the param. Only in deep mode, guarded by length + entropy.
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
                continue  # don't also count as a candidate

            # SECONDARY: high-entropy cross-domain param value.
            if len(decoded) >= MIN_PRIMARY_VALUE_LEN and total_bits(decoded) >= min_bits:
                req_candidates.append(
                    {
                        "param": param_name,
                        "value_preview": decoded[:12] + ("…" if len(decoded) > 12 else ""),
                        "total_bits": round(total_bits(decoded), 1),
                        "to_domain": to_domain,
                        "request_url": url,
                    }
                )

        # PATH: if this cross-domain request hits a known sync endpoint, attach
        # the endpoint evidence to every identifier row it produced. The rows
        # *are* the corroborating identifier (a confirmed cookie or a candidate),
        # so no separate identifier check is needed. ``kind`` records which:
        # "cookie" rows are the overlap with confirmed, "entropy" rows are
        # exclusive to this layer.
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
# I/O
# ---------------------------------------------------------------------------


def iter_site_files(data_dir: str):
    pattern = os.path.join(data_dir, "**", "*.json")
    paths = sorted(glob.glob(pattern, recursive=True))
    if not paths:
        print(f"No JSON files found in: {data_dir}", file=sys.stderr)
        sys.exit(1)
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                yield path, json.load(fh)
        except Exception as exc:
            print(f"  [!] Skipping {path}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_report(per_site: list[dict]) -> None:
    pair_counter: Counter = Counter()
    path_pair_counter: Counter = Counter()
    total_confirmed = 0
    total_candidates = 0
    total_substring = 0
    total_path = 0
    total_path_excl = 0
    sites_with_sync = 0
    sites_with_path = 0

    for entry in per_site:
        sync = entry["cookie_syncing"]
        if sync["confirmed"]:
            sites_with_sync += 1
        total_confirmed += len(sync["confirmed"])
        total_candidates += len(sync["candidates"])
        total_substring += sum(
            1 for ev in sync["confirmed"] if ev.get("match") == "substring"
        )
        for ev in sync["confirmed"]:
            pair_counter[(sync["site_domain"], ev["to_domain"])] += 1

        # Path-sync evidence now lives as a ``path_sync`` annotation on
        # confirmed/candidate rows. Count it per request (dedup across the
        # possibly-many rows of one request) so the totals mean "requests".
        confirmed_urls = {ev["request_url"] for ev in sync["confirmed"]}
        seen: dict[str, str] = {}  # request_url -> to_domain
        for ev in sync["confirmed"] + sync["candidates"]:
            if "path_sync" in ev:
                seen.setdefault(ev["request_url"], ev["to_domain"])
        if seen:
            sites_with_path += 1
        total_path += len(seen)
        for url, to in seen.items():
            if url not in confirmed_urls:
                total_path_excl += 1
            path_pair_counter[(sync["site_domain"], to)] += 1

    print(f"\n{'='*70}")
    print("  Cookie Syncing Report")
    print(f"  Sites analysed         : {len(per_site)}")
    print(f"  Sites with confirmed   : {sites_with_sync}")
    print(f"  Confirmed sync events  : {total_confirmed}")
    print(f"    of which embedded    : {total_substring}")
    print(f"  Candidate sync events  : {total_candidates}")
    print(f"  Sites with path-sync   : {sites_with_path}")
    print(f"  Path-sync events       : {total_path}")
    print(f"    excl. of confirmed   : {total_path_excl}")
    print(f"{'='*70}\n")

    if pair_counter:
        print("  Top confirmed sync domain pairs (from -> to):")
        for (frm, to), count in pair_counter.most_common(30):
            print(f"    {frm:>30}  ->  {to:<30}  ({count})")
        print()

    if path_pair_counter:
        print("  Top sync-endpoint domain pairs (from -> to):")
        for (frm, to), count in path_pair_counter.most_common(30):
            print(f"    {frm:>30}  ->  {to:<30}  ({count})")
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Detect cookie syncing from stored request URLs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("data_dir", help="Directory of site JSON files (Chromium crawl).")
    p.add_argument(
        "--min-bits",
        type=float,
        default=DEFAULT_MIN_BITS,
        help="total_bits cutoff for high-entropy candidate params.",
    )
    p.add_argument(
        "--deep-match",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Also match base64-encoded and embedded (substring) cookie values. "
        "Catches more transformed syncs at some false-positive risk.",
    )
    p.add_argument(
        "--path-match",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Detect URL-path / param-name sync endpoints (e.g. /usersync, "
        "partner_uid), corroborated by an identifier on the same request.",
    )
    p.add_argument(
        "--annotate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write a 'cookie_syncing' field back into each site JSON.",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Optional path to write the aggregated per-site results as JSON.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    path_detector = PathSyncDetector() if args.path_match else None

    per_site = []
    for path, data in iter_site_files(args.data_dir):
        if "requests" not in data:
            # Non-Chromium crawl or pre-upgrade data — nothing to analyse.
            continue
        sync = analyze_site(
            data,
            min_bits=args.min_bits,
            deep=args.deep_match,
            path_detector=path_detector,
        )
        per_site.append({"source_file": path, "cookie_syncing": sync})

        if args.annotate:
            data["cookie_syncing"] = sync
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=4)

    if not per_site:
        print(
            "No site JSON with a 'requests' field found. Cookie syncing needs a "
            "Chromium-family crawl produced after the requests-persistence change "
            "(re-run get_cookies.py).",
            file=sys.stderr,
        )
        sys.exit(1)

    print_report(per_site)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(per_site, fh, indent=2)
        print(f"Results written to: {args.out}")


if __name__ == "__main__":
    main()
