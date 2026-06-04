"""
Shared loader + console reporter for cookie-syncing *subtype* plots.

Breaks the syncs that scripts/find_cookie_syncing.py writes (the per-site
``cookie_syncing`` field) down into the research-recognised subtype dimensions,
at **per-param-row** granularity:

  * tier      — the confidence ladder, with the URL/param-name regex layer folded
                in:  ``confirmed`` (cookie-value match)  >  ``endpoint-named`` (a
                high-entropy candidate row that ALSO carries a ``path_sync``
                annotation, i.e. it landed on a known sync endpoint / ID-named
                param)  >  ``candidate`` (high-entropy only, no endpoint).
  * carrier   — the mechanism the identifier rode on, from the request's Chromium
                resource ``type``:  pixel / beacon / script / xhr-fetch /
                redirect-navigation / other.  A derivable proxy for the academic
                initiator taxonomy (embedded pixel vs script vs JS-call vs nav).
  * tracker   — whether the receiving request matched a known tracker
                (EasyPrivacy), i.e. ``easyprivacy.matched``.
  * encoding  — confirmed rows only: how the value was transformed to match a
                cookie:  raw / url-encoded / base64 / substring.

``carrier`` and ``tracker`` are not stored on the sync rows; they are recovered by
joining each row's ``request_url`` back to the raw ``requests`` array of the same
site JSON (each entry has ``url``, ``type``, ``easyprivacy``).  ``encoding`` is
recomputed from the param value vs the site's cookie values, reusing the detector's
own ``_norm_forms`` / ``_b64_variants`` helpers so the logic stays in one place.

This module is imported by the three plot scripts (plot_sync_sankey.py,
plot_sync_subtypes_bar.py, plot_sync_heatmap.py); it is not a CLI itself.
"""

from __future__ import annotations

import os
import sys
from collections import Counter
from urllib.parse import parse_qsl, unquote, urlparse

# Repo root on path so we can import the detector's pure helpers (DRY) and reuse
# the plot utils. Mirrors how find_cookie_syncing.py adds the root itself.
_THIS = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_THIS, "..", ".."))  # repo root
sys.path.insert(0, os.path.join(_THIS, ".."))         # scripts/

from find_cookie_syncing import _b64_variants, _registered_domain  # noqa: E402

import utils  # noqa: E402  (scripts/plot_scripts on sys.path via the importing script)

# ---------------------------------------------------------------------------
# Subtype vocabularies (ordered) + on-theme colors
# ---------------------------------------------------------------------------

TIERS = ["confirmed", "endpoint-named", "candidate"]
CARRIERS = ["pixel", "beacon", "script", "xhr/fetch", "redirect/navigation", "other"]
ENCODINGS = ["raw", "url-encoded", "base64", "substring"]
TRACKER_LABELS = ["tracker", "non-tracker"]

# Map Chromium resource type -> carrier subtype.
_CARRIER_BY_TYPE = {
    "Image": "pixel",
    "Ping": "beacon",
    "Script": "script",
    "XHR": "xhr/fetch",
    "Fetch": "xhr/fetch",
    "Document": "redirect/navigation",
    "Prefetch": "redirect/navigation",
}

# Stable color per category, drawn from the shared palette so every plot agrees.
_C = utils.COLORS


def _color_map(categories: list[str]) -> dict[str, str]:
    return {cat: _C[i % len(_C)] for i, cat in enumerate(categories)}


TIER_COLORS = {
    "confirmed": utils.ACCENT,       # strongest -> primary highlight
    "endpoint-named": utils.ACCENT2,  # promoted middle tier
    "candidate": utils.MID,          # weakest
}
CARRIER_COLORS = _color_map(CARRIERS)
ENCODING_COLORS = _color_map(ENCODINGS)
TRACKER_COLORS = {"tracker": utils.ACCENT, "non-tracker": utils.LIGHT}

# Which vocabulary + color map backs each dimension name.
DIMENSIONS = {
    "tier": (TIERS, TIER_COLORS),
    "carrier": (CARRIERS, CARRIER_COLORS),
    "encoding": (ENCODINGS, ENCODING_COLORS),
    "tracker": (TRACKER_LABELS, TRACKER_COLORS),
}


def carrier_of(req_type: str) -> str:
    return _CARRIER_BY_TYPE.get(req_type or "", "other")


# ---------------------------------------------------------------------------
# Encoding classification (confirmed rows only)
# ---------------------------------------------------------------------------


def _encoding_of(raw_value: str, cookie_value: str, match_kind: str) -> str:
    """Classify how ``raw_value`` (the param) encodes ``cookie_value``.

    ``raw`` (sent verbatim) / ``url-encoded`` (percent-encoded) / ``base64`` /
    ``substring`` (embedded match, deep mode). Falls back to ``raw`` when the
    cookie value is unavailable, since the detector already proved a match.
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
    # base64 of the cookie value, in either direction.
    if raw_value in _b64_variants(cookie_value) or decoded in _b64_variants(cookie_value):
        return "base64"
    if cookie_value in _b64_variants(decoded):
        return "base64"
    return "raw"


def _param_value_in(url: str, param: str) -> str:
    """Return the raw (still-encoded) value of ``param`` in ``url``'s query."""
    for name, val in parse_qsl(urlparse(url).query, keep_blank_values=False):
        if name == param:
            return val
    return ""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_sync_events(data_dir: str) -> list[dict]:
    """Return one event dict per confirmed/candidate **param row** across all sites.

    Each event: ``{from_domain, to_domain, carrier, tracker, tier, encoding}``
    where ``tracker`` is a bool and ``encoding`` is set on confirmed rows only
    (``None`` otherwise).
    """
    events: list[dict] = []
    annotated = 0

    for _domain, _browser, data in utils._iter_cookie_files(data_dir):
        sync = data.get("cookie_syncing")
        if not sync:
            continue
        annotated += 1
        site_domain = sync.get("site_domain") or _registered_domain(
            data.get("target_url", "")
        )

        # url -> (carrier, tracker) join table from the raw request log.
        req_meta: dict[str, tuple[str, bool]] = {}
        for req in data.get("requests", []):
            url = req.get("url")
            if not url:
                continue
            ep = req.get("easyprivacy")
            tracker = bool(ep.get("matched")) if isinstance(ep, dict) else False
            req_meta.setdefault(url, (carrier_of(req.get("type", "")), tracker))

        # cookie name -> value, for encoding classification.
        cookie_val = {c.get("name", ""): (c.get("value") or "") for c in data.get("cookies", [])}

        def _meta(url: str) -> tuple[str, bool]:
            return req_meta.get(url, ("other", False))

        for row in sync.get("confirmed", []):
            url = row.get("request_url", "")
            carrier, tracker = _meta(url)
            raw_value = _param_value_in(url, row.get("param", ""))
            events.append(
                {
                    "from_domain": site_domain,
                    "to_domain": row.get("to_domain", ""),
                    "carrier": carrier,
                    "tracker": tracker,
                    "tier": "confirmed",
                    "encoding": _encoding_of(
                        raw_value,
                        cookie_val.get(row.get("cookie_name", ""), ""),
                        row.get("match", "exact"),
                    ),
                }
            )

        for row in sync.get("candidates", []):
            url = row.get("request_url", "")
            carrier, tracker = _meta(url)
            tier = "endpoint-named" if "path_sync" in row else "candidate"
            events.append(
                {
                    "from_domain": site_domain,
                    "to_domain": row.get("to_domain", ""),
                    "carrier": carrier,
                    "tracker": tracker,
                    "tier": tier,
                    "encoding": None,
                }
            )

    if annotated == 0:
        raise ValueError(
            "No 'cookie_syncing' annotations found. Run "
            "`python scripts/find_cookie_syncing.py <dir> --annotate` first "
            "(needs a Chromium crawl with the 'requests' field)."
        )
    return events


# ---------------------------------------------------------------------------
# Helpers shared by the plot scripts
# ---------------------------------------------------------------------------


def dim_value(event: dict, dimension: str) -> str:
    """Return the categorical label of ``event`` along ``dimension``."""
    if dimension == "tracker":
        return "tracker" if event["tracker"] else "non-tracker"
    return event.get(dimension)


def topn_with_other(counter: Counter, n: int, other_label: str = "(other)") -> list[str]:
    """Top-``n`` keys by count, with the remainder folded into ``other_label``."""
    top = [k for k, _ in counter.most_common(n)]
    if len(counter) > n:
        top.append(other_label)
    return top


def fold_other(domain: str, keep: set[str], other_label: str = "(other)") -> str:
    return domain if domain in keep else other_label


# ---------------------------------------------------------------------------
# Console report (every plot script calls this on finish)
# ---------------------------------------------------------------------------


def print_subtype_report(events: list[dict]) -> None:
    total = len(events)
    print(f"\n{'='*70}")
    print("  Cookie-Sync Subtype Breakdown")
    print(f"  Total sync rows (per-param) : {total}")
    print(f"{'='*70}")
    if not total:
        print("  (no events)\n")
        return

    for dim, (order, _colors) in DIMENSIONS.items():
        # None values (e.g. encoding on candidate rows) don't belong to the dim.
        counts = Counter(
            v for e in events if (v := dim_value(e, dim)) is not None
        )
        # encoding only applies to confirmed rows; its denominator is those rows.
        denom = sum(counts.values())
        print(f"\n  By {dim}:" + (" (confirmed rows only)" if dim == "encoding" else ""))
        seen = set()
        for label in order + sorted(k for k in counts if k not in order):
            if label in seen:
                continue
            seen.add(label)
            c = counts.get(label)
            if not c:
                continue
            pct = 100.0 * c / denom if denom else 0.0
            bar = "#" * int(round(pct / 5))
            print(f"    {label:<22} {c:>7}  {pct:5.1f}%  {bar}")
    print()
