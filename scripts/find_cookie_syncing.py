"""
scripts/find_cookie_syncing.py
------------------------------
Detect *cookie syncing* — trackers sharing a user identifier with one another by
passing a cookie's value to a different domain through request parameters.

This is post-hoc analysis over the ``requests`` field that get_cookies.py now
stores for Chromium-family crawls (full request URLs with query strings), plus
the ``cookies`` already in each site JSON.

Two layers of evidence (per the agreed design):

  PRIMARY (strong)
      A cookie value observed on the site (and its URL-encoded form) appears as
      a query-parameter value in a request sent to a *different registered
      domain*. This is direct proof the identifier crossed a domain boundary.

  SECONDARY (candidate)
      A query-parameter value sent cross-domain is high-entropy and long enough
      to look like a UID, even though we did not match it to a known cookie.
      Reported separately as a weaker "candidate" signal.

For each site this writes a ``cookie_syncing`` field back into the JSON (like
process_cookies.py adds party_type) and prints a cross-site aggregate report of
which domain pairs sync identifiers.

Usage
-----
    python scripts/find_cookie_syncing.py cookies_data/chromium
    python scripts/find_cookie_syncing.py cookies_data --min-bits 36
    python scripts/find_cookie_syncing.py cookies_data --no-annotate --out syncs.json
    python scripts/find_cookie_syncing.py cookies_data --deep-match   # base64 + embedded
"""

from __future__ import annotations

import argparse
import base64
import glob
import json
import os
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


def analyze_site(data: dict, min_bits: float, deep: bool = False) -> dict:
    """Detect sync events for one loaded site JSON.

    With ``deep`` the PRIMARY matcher also recognises base64-encoded forms of a
    cookie value, and embedded (substring) occurrences of long, high-entropy
    values. This catches more transformed syncs at the cost of some false-
    positive risk, so it is opt-in.

    Returns a ``cookie_syncing`` dict:
        {
          "site_domain": <registered domain of the page>,
          "confirmed": [ {cookie_name, param, to_domain, request_url, match}, ...],
          "candidates": [ {param, value_preview, total_bits, to_domain, request_url}, ...],
        }
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
                confirmed.append(
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
                candidates.append(
                    {
                        "param": param_name,
                        "value_preview": decoded[:12] + ("…" if len(decoded) > 12 else ""),
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
    total_confirmed = 0
    total_candidates = 0
    total_substring = 0
    sites_with_sync = 0

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

    print(f"\n{'='*70}")
    print("  Cookie Syncing Report")
    print(f"  Sites analysed         : {len(per_site)}")
    print(f"  Sites with confirmed   : {sites_with_sync}")
    print(f"  Confirmed sync events  : {total_confirmed}")
    print(f"    of which embedded    : {total_substring}")
    print(f"  Candidate sync events  : {total_candidates}")
    print(f"{'='*70}\n")

    if pair_counter:
        print("  Top confirmed sync domain pairs (from -> to):")
        for (frm, to), count in pair_counter.most_common(30):
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

    per_site = []
    for path, data in iter_site_files(args.data_dir):
        if "requests" not in data:
            # Non-Chromium crawl or pre-upgrade data — nothing to analyse.
            continue
        sync = analyze_site(data, min_bits=args.min_bits, deep=args.deep_match)
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
