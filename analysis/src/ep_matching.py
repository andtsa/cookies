from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from client.trackers.matcher import EasyPrivacyMatcher

    from .records import SiteRaw

EpResult = tuple[frozenset[str], int, float]
MatchKey = tuple[str, str, str]


def ep_data_for_site(
    site: "SiteRaw",
    matcher: "EasyPrivacyMatcher",
    match_cache: dict[MatchKey, bool],
) -> EpResult:
    """Return ``(matched_url_set, count, pct)`` of EasyPrivacy-matched requests.

    For JSON files produced by an older crawler the data is read directly from
    the stored ``easyprivacy`` field (cheap dict lookups). For new files (field
    absent) ``matcher`` is run over the stored request URLs.

    ``match_cache`` memoises ``matcher.match(url, doc_url, type)`` verdicts —
    a pure function of those three values — and is **mutated in place** so
    repeated triples (extremely common: the same tracker request recurs across
    sites and across the crawl's per-{country,browser} re-visits of the same
    site) become dict lookups instead of re-running the expensive
    ``_find_matching_rule`` regex scan. Callers own the cache's lifetime
    (in-process memo vs. a worker-local one) and persistence.
    """
    requests = site.requests
    if not requests:
        return frozenset(), 0, 0.0

    total = len(requests)

    if any("easyprivacy" in r for r in requests):
        # Old crawl: EP data already stored in JSON — read it back (cheap)
        matched_urls = frozenset(
            r["url"]
            for r in requests
            if (r.get("easyprivacy") or {}).get("matched") and r.get("url")
        )
        count = sum(1 for r in requests if (r.get("easyprivacy") or {}).get("matched"))
    else:
        # New crawl: run the matcher over the stored request URLs, memoising
        # verdicts on (url, document_url, type) — match()'s actual inputs.
        target_url = site.target_url
        matched: set[str] = set()
        count = 0
        for r in requests:
            url = r.get("url", "")
            if not url:
                continue
            doc_url = r.get("document_url", "") or target_url
            rtype = r.get("type", "")
            key = (url, doc_url, rtype)
            is_match = match_cache.get(key)
            if is_match is None:
                is_match = matcher.match(url, doc_url, rtype).matched
                match_cache[key] = is_match
            if is_match:
                matched.add(url)
                count += 1
        matched_urls = frozenset(matched)

    pct = round(count / total * 100, 1) if total else 0.0
    return matched_urls, count, pct


def needs_live_ep_matching(site: "SiteRaw") -> bool:
    """True when at least one cookie lacks ``setter_ep_matched`` (new-format crawl)."""
    return any("setter_ep_matched" not in c for c in site.cookies)


def needs_ep_data(site: "SiteRaw") -> bool:
    """True when *anything* this site feeds into would call ``ep_data_for_site``.

    There are two independent triggers for ``_ep_data_for_site`` —
    ``_build_cookies`` calls it per-cookie via :func:`needs_live_ep_matching`
    (cookie-level: any cookie missing ``setter_ep_matched``), and
    ``_build_sites`` calls it separately for the aggregate
    ``easyprivacy_requests``/``easyprivacy_pct`` columns whenever
    ``summary.requests`` lacks those fields (site-level).

    A site can fail the site-level check without failing the cookie-level one
    (cookies annotated, but the crawler's per-site summary wasn't) — so
    prefetch site-selection must check *both*, or such a site silently falls
    through to a cold, single-threaded ``_ep_matcher`` build + live match in
    the main process during ``_build_sites`` (which is exactly what produces
    that one extra "EasyPrivacyMatcher ready" line after every worker reports
    done).
    """
    if needs_live_ep_matching(site):
        return True
    sr = (site.data.get("summary", {}) or {}).get("requests", {}) or {}
    return "easyprivacy" not in sr or "easyprivacy_pct" not in sr
