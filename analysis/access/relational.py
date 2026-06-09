from __future__ import annotations

from collections import defaultdict
from functools import cached_property

from client.trackers.js import build_cookie_domain_index, find_cross_domain_cookies

from ..src import reads, relational_cache, sharing, syncing
from ..src.helpers import registered_domain
from ..src.progress import track


def _relational_key(self) -> str | None:
    """Disk-cache key for the sync-subtype / third-party-read tables.

    Reuses the annotation fingerprint (:meth:`FrameAccess._classified_key`) when
    available, so these tables share the data + ``sync_min_bits`` invalidation.
    """
    getter = getattr(self, "_classified_key", None)
    return getter() if getter is not None else None


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

    def syncing(self, *, deep: bool = False, path: bool = True) -> list[dict]:
        ckey = ("syncing", deep, path)
        if ckey in self._cache:
            return self._cache[ckey]
        detector = syncing.PathSyncDetector() if path else None
        events = []
        for site in track(
            self._raw_sites,
            desc="cookie syncing",
            total=len(self._raw_sites),
            unit=" sites",
        ):
            result = syncing.analyze_site(
                site.data,
                min_bits=self.sync_min_bits,
                deep=deep,
                path_detector=detector,
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

    def sync_subtype_rows(self, *, deep: bool = False) -> list[dict]:
        """One row per confirmed/candidate sync param, with subtype dimensions.

        Each row::

            {country, browser, from_domain, to_domain,
             carrier, tracker, tier, encoding}

        where ``tier`` is ``confirmed`` | ``endpoint-named`` (a candidate row
        that also landed on a sync endpoint) | ``candidate``; ``carrier`` is the
        request mechanism; ``tracker`` is whether the receiving request matched
        EasyPrivacy; and ``encoding`` (confirmed rows only, else ``None``) is how
        the value was transformed. Backs the sync subtype/heatmap/sankey plots
        without any on-disk ``cookie_syncing`` annotation.
        """
        ckey = ("sync_subtype_rows", deep)
        if ckey in self._cache:
            return self._cache[ckey]

        # Disk cache (default deep=False variant only — the one plots/annotate use).
        rkey = _relational_key(self) if not deep else None
        if not getattr(self, "rebuild", False):
            cached = relational_cache.load(
                getattr(self, "cache_dir", None), rkey, "subtypes"
            )
            if cached is not None:
                self._cache[ckey] = cached
                return cached

        rows: list[dict] = []
        for site in track(
            self._raw_sites,
            desc="sync subtypes",
            total=len(self._raw_sites),
            unit=" sites",
        ):
            data = site.data
            result = syncing.analyze_site(
                data,
                min_bits=self.sync_min_bits,
                deep=deep,
                path_detector=syncing.PathSyncDetector(),
            )
            if not (result["confirmed"] or result["candidates"]):
                continue
            site_domain = result["site_domain"]

            # url -> (carrier, tracker) join from the raw request log.
            req_meta: dict[str, tuple[str, bool]] = {}
            for req in data.get("requests", []) or []:
                url = req.get("url")
                if not url:
                    continue
                ep = req.get("easyprivacy")
                tracker = bool(ep.get("matched")) if isinstance(ep, dict) else False
                req_meta.setdefault(
                    url, (syncing.carrier_of(req.get("type", "")), tracker)
                )

            cookie_val = {
                c.get("name", ""): (c.get("value") or "")
                for c in (data.get("cookies", []) or [])
            }

            def _meta(url: str) -> tuple[str, bool]:
                return req_meta.get(url, ("other", False))

            for row in result["confirmed"]:
                url = row.get("request_url", "")
                carrier, tracker = _meta(url)
                raw_value = syncing.param_value_in(url, row.get("param", ""))
                rows.append(
                    {
                        "country": site.country,
                        "browser": site.browser,
                        "from_domain": site_domain,
                        "to_domain": row.get("to_domain", ""),
                        "carrier": carrier,
                        "tracker": tracker,
                        "tier": "confirmed",
                        "encoding": syncing.encoding_of(
                            raw_value,
                            cookie_val.get(row.get("cookie_name", ""), ""),
                            row.get("match", "exact"),
                        ),
                    }
                )

            for row in result["candidates"]:
                url = row.get("request_url", "")
                carrier, tracker = _meta(url)
                rows.append(
                    {
                        "country": site.country,
                        "browser": site.browser,
                        "from_domain": site_domain,
                        "to_domain": row.get("to_domain", ""),
                        "carrier": carrier,
                        "tracker": tracker,
                        "tier": "endpoint-named" if "path_sync" in row else "candidate",
                        "encoding": None,
                    }
                )

        if rkey is not None:
            relational_cache.save(
                getattr(self, "cache_dir", None), rkey, "subtypes", rows
            )
        self._cache[ckey] = rows
        return rows

    def cross_domain_reads(self, min_domains: int = 2) -> list[dict]:
        ckey = ("cross_domain_reads", min_domains)
        if ckey in self._cache:
            return self._cache[ckey]

        # partition sessions by (country, browser) so "read across N domains"
        # reflects cross-site behaviour observed within a single crawl,
        # not the same physical site being visited under
        # different country/browser combinations
        sessions_by_crawl: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for site in track(
            self._raw_sites,
            desc="cross-domain reads",
            total=len(self._raw_sites),
            unit=" sites",
        ):
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

    def third_party_reads(self) -> list[dict]:
        """Cross-party JS cookie reads, one row per (cookie, site, reader).

        Each row::

            {country, browser, cookie_name, visited_domain,
             reader_domain, reader_script}

        ``reader_domain`` is the registered domain of the first script in the
        read's JS call-stack; first-party reads (reader == visited) are dropped.
        This is the in-engine replacement for the old ``reads_filtered.json``,
        backing the third-party-reader plots.
        """
        ckey = ("third_party_reads",)
        if ckey in self._cache:
            return self._cache[ckey]

        rkey = _relational_key(self)
        if not getattr(self, "rebuild", False):
            cached = relational_cache.load(
                getattr(self, "cache_dir", None), rkey, "tpreads"
            )
            if cached is not None:
                self._cache[ckey] = cached
                return cached

        result: list[dict] = []
        for site in track(
            self._raw_sites,
            desc="third-party reads",
            total=len(self._raw_sites),
            unit=" sites",
        ):
            ja = site.js_activity
            if not ja.get("reads"):
                continue
            visited = registered_domain(site.target_url) or site.domain
            session = {"visited_domain": visited, "reads": ja.get("reads", [])}
            for rec in reads.third_party_reads([session]):
                rec["country"] = site.country
                rec["browser"] = site.browser
                result.append(rec)

        relational_cache.save(getattr(self, "cache_dir", None), rkey, "tpreads", result)
        self._cache[ckey] = result
        return result
