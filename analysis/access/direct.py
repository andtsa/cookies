from __future__ import annotations

from functools import cached_property
from pathlib import Path

from client.trackers import TrackerList
from client.trackers.name_similarity import cluster_names

from ..src.loading import load_site, load_site_lists, site_paths
from ..src.records import SiteRaw


class RawAccess:
    # ------------------------------------------------------------------ raw
    def site_files(self) -> list[Path]:
        return site_paths(self.data_dir)

    @cached_property
    def _raw_sites(self) -> list[SiteRaw]:
        sites = []
        for path in self.site_files():
            site = load_site(path, self.data_dir)
            if site is not None:
                sites.append(site)
        return sites

    def iter_raw_sites(self):
        yield from self._raw_sites

    def iter_cookies(self):
        """yield `(site, cookie_dict)` for every cookie."""
        for site in self._raw_sites:
            for cookie in site.cookies:
                yield site, cookie

    # helpers
    @cached_property
    def _tracker_list(self) -> TrackerList:
        tl = TrackerList()
        tl.load(cache_dir=self.tracker_cache_dir, trackers=self.tracker_lists)
        return tl

    @cached_property
    def _ep_matcher(self):
        """EasyPrivacy request-URL matcher, built lazily from the tracker list."""
        from client.trackers.matcher import EasyPrivacyMatcher

        return EasyPrivacyMatcher(self._tracker_list._easyprivacy)

    def _ep_data_for_site(self, site: "SiteRaw") -> tuple[frozenset[str], int, float]:
        """Return (matched_url_set, count, pct) of EasyPrivacy-matched requests.

        For JSON files produced by an older crawler the data is read directly
        from the stored ``easyprivacy`` field.  For new files (field absent) the
        matcher is run over the stored request URLs so the analysis still works.
        Results are cached per site path to avoid double computation when both
        ``_build_cookies`` and ``_build_sites`` call this method.
        """
        if site.path in self._ep_cache:
            return self._ep_cache[site.path]

        requests = site.requests
        if not requests:
            result: tuple[frozenset[str], int, float] = (frozenset(), 0, 0.0)
            self._ep_cache[site.path] = result
            return result

        total = len(requests)

        if any("easyprivacy" in r for r in requests):
            # Old crawl: EP data already stored in JSON, read it back
            matched_urls = frozenset(
                r["url"]
                for r in requests
                if (r.get("easyprivacy") or {}).get("matched") and r.get("url")
            )
            count = sum(
                1 for r in requests if (r.get("easyprivacy") or {}).get("matched")
            )
        else:
            # New crawl: run the matcher over the stored request URLs
            target_url = site.target_url
            matched: set[str] = set()
            count = 0
            for r in requests:
                url = r.get("url", "")
                doc_url = r.get("document_url", "") or target_url
                rtype = r.get("type", "")
                if url and self._ep_matcher.match(url, doc_url, rtype).matched:
                    matched.add(url)
                    count += 1
            matched_urls = frozenset(matched)

        pct = round(count / total * 100, 1) if total else 0.0
        result = (matched_urls, count, pct)
        self._ep_cache[site.path] = result
        return result

    @cached_property
    def _site_list_map(self) -> dict[str, tuple[str, int]]:
        return load_site_lists(self.site_lists)

    @cached_property
    def name_families(self) -> dict[str, str]:
        names = {c.get("name", "") for _, c in self.iter_cookies() if c.get("name")}
        return cluster_names(names, max_edit_distance=self.cluster_max_edit_distance)

    def _tracker_fields(self, cookie: dict) -> tuple[bool, list[str], str | None]:
        """Return ``(is_tracker, lists, matched_domain)`` for a cookie.

        Reads flat ``tracker_lists`` / ``tracker_provider`` fields written by the
        crawler. Falls back to live detection only when ``recompute_trackers`` is set.
        """
        if not self.recompute_trackers:
            lists = list(cookie.get("tracker_lists") or [])
            return bool(lists), lists, cookie.get("tracker_provider")
        det = self._tracker_list.is_tracker(cookie)
        if det is None:
            return False, [], None
        return bool(det.lists), list(det.lists), det.matched_domain
