"""
analysis._relational
--------------------
``_RelationalMixin`` — the cross-site / cross-cookie analyses of
:class:`~analysis.CookieDataset`: identifier sharing (:meth:`shared`),
cookie-syncing detection (:meth:`syncing`), and cross-domain JS reads
(:meth:`cross_domain_reads`), plus their cached-property shortcuts
(:attr:`shared_groups`, :attr:`sync_events`).

These are the expensive, full-dataset, relational passes that
:attr:`~analysis.CookieDataset.classified_cookies` is built from — each scans
every site (or every cookie occurrence) once and is memoised in ``self._cache``
so repeat calls with the same parameters are free.

Split into its own file purely for readability — at runtime this is just part
of ``CookieDataset``; nothing here is meant to be used as a mixin elsewhere.
"""

from __future__ import annotations

from functools import cached_property

from client.trackers.js import build_cookie_domain_index, find_cross_domain_cookies

from ..src import sharing, syncing
from ..src.helpers import registered_domain


class RelationalAccess:
    # -------------------------------------------------------- relational analyses
    def shared(
        self,
        *,
        match_mode: str = "name-md5",
        min_sites: int = 2,
        trackers_only: bool = False,
        third_party_only: bool = False,
    ) -> list[dict]:
        ckey = ("shared", match_mode, min_sites, trackers_only, third_party_only)
        if ckey in self._cache:
            return self._cache[ckey]
        cols = [
            "name",
            "md5_value",
            "total_bits",
            "registered_domain",
            "cookie_type",
            "party_type",
            "is_tracker",
            "country",
            "browser",
        ]
        occ = self.cookies[cols].copy()
        # "site" identity = the crawled page (country+browser+domain) so the same
        # site under two browsers isn't conflated.
        occ["site"] = (
            self.cookies["country"]
            + "/"
            + self.cookies["browser"]
            + "/"
            + self.cookies["domain"]
        )
        occurrences = occ.to_dict("records")
        index = sharing.build_index(occurrences, match_mode, self.name_families)
        result = sharing.find_shared(index, min_sites, trackers_only, third_party_only)
        self._cache[ckey] = result
        return result

    @cached_property
    def shared_groups(self) -> list[dict]:
        return self.shared()

    def syncing(self, *, deep: bool = False) -> list[dict]:
        ckey = ("syncing", deep)
        if ckey in self._cache:
            return self._cache[ckey]
        events = []
        for site in self._raw_sites:
            result = syncing.analyze_site(
                site.data, min_bits=self.sync_min_bits, deep=deep
            )
            if result["confirmed"] or result["candidates"]:
                events.append(
                    {
                        "country": site.country,
                        "browser": site.browser,
                        "domain": site.domain,
                        **result,
                    }
                )
        self._cache[ckey] = events
        return events

    @cached_property
    def sync_events(self) -> list[dict]:
        return self.syncing()

    def cross_domain_reads(self, min_domains: int = 2) -> list[dict]:
        ckey = ("cross_domain_reads", min_domains)
        if ckey in self._cache:
            return self._cache[ckey]
        sessions = []
        for site in self._raw_sites:
            ja = site.js_activity
            if not ja.get("reads"):
                continue
            sessions.append(
                {
                    "visited_domain": registered_domain(site.target_url) or site.domain,
                    "reads": ja.get("reads", []),
                    "writes": ja.get("writes", []),
                }
            )
        index = build_cookie_domain_index(sessions)
        result = find_cross_domain_cookies(index, min_domains=min_domains)
        self._cache[ckey] = result
        return result
