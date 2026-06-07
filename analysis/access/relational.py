from __future__ import annotations

from collections import defaultdict
from functools import cached_property

from client.trackers.js import build_cookie_domain_index, find_cross_domain_cookies

from ..src import sharing, syncing
from ..src.helpers import registered_domain


class RelationalAccess:
    # relational analyses
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
        # Within a single (country, browser) crawl,
        # "site" identity reduces to just the crawled domain
        occ["site"] = self.cookies["domain"]
        occurrences = occ.to_dict("records")

        # partition by (country, browser) *before* indexing
        # so each crawl is judged on its own cross-site spread,
        # not pooled with every other crawl in the dataset
        by_crawl: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for o in occurrences:
            by_crawl[(o["country"], o["browser"])].append(o)

        result: list[dict] = []
        for (country, browser), crawl_occs in by_crawl.items():
            index = sharing.build_index(crawl_occs, match_mode, self.name_families)
            groups = sharing.find_shared(
                index, min_sites, trackers_only, third_party_only
            )
            for group in groups:
                group["country"] = country
                group["browser"] = browser
            result.extend(groups)
        result.sort(key=lambda r: r["site_count"], reverse=True)
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

        # partition sessions by (country, browser) so "read across N domains"
        # reflects cross-site behaviour observed within a single crawl,
        # not the same physical site being visited under
        # different country/browser combinations
        sessions_by_crawl: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for site in self._raw_sites:
            ja = site.js_activity
            if not ja.get("reads"):
                continue
            sessions_by_crawl[(site.country, site.browser)].append(
                {
                    "visited_domain": registered_domain(site.target_url) or site.domain,
                    "reads": ja.get("reads", []),
                    "writes": ja.get("writes", []),
                }
            )

        result: list[dict] = []
        for (country, browser), sessions in sessions_by_crawl.items():
            index = build_cookie_domain_index(sessions)
            groups = find_cross_domain_cookies(index, min_domains=min_domains)
            for group in groups:
                group["country"] = country
                group["browser"] = browser
            result.extend(groups)
        result.sort(key=lambda r: r["domain_count"], reverse=True)
        self._cache[ckey] = result
        return result
