from __future__ import annotations

from functools import cached_property
from pathlib import Path

from client.trackers import TrackerList
from client.trackers.name_similarity import cluster_names

from ..src import ep_cache, ep_matching
from ..src.loading import load_site, load_site_lists, site_paths
from ..src.records import SiteRaw


def _ep_prefetch_worker(
    path_strs: list[str],
    data_dir: str,
    tracker_list_names: list[str],
    tracker_cache_dir: str,
    seed_match_cache: dict["ep_matching.MatchKey", bool],
) -> tuple[dict[str, "ep_matching.EpResult"], dict["ep_matching.MatchKey", bool]]:
    from client.trackers import Detections, TrackerList
    from client.trackers.matcher import EasyPrivacyMatcher

    tl = TrackerList()
    tl.load(
        cache_dir=tracker_cache_dir,
        trackers={Detections[name] for name in tracker_list_names},
    )
    matcher = EasyPrivacyMatcher(tl._easyprivacy)

    seed_keys = frozenset(seed_match_cache)
    local_match_cache: dict[ep_matching.MatchKey, bool] = dict(seed_match_cache)
    ep_results: dict[str, "ep_matching.EpResult"] = {}

    for path_str in path_strs:
        path = Path(path_str)
        site = load_site(path, data_dir)
        if site is None:
            continue
        ep_results[path_str] = ep_matching.ep_data_for_site(
            site, matcher, local_match_cache
        )

    new_entries = {k: v for k, v in local_match_cache.items() if k not in seed_keys}
    return ep_results, new_entries


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

    @cached_property
    def _ep_match_fingerprint(self) -> str:
        """Identifies *which* EasyPrivacy ruleset the persisted memo belongs to.

        Computed from the cached filter-list file(s) under
        ``tracker_cache_dir`` (stat-based — cheap, no parsing). If the list is
        refreshed, this changes and the on-disk memo is treated as stale.
        """
        return ep_cache.ruleset_fingerprint(self.tracker_cache_dir)

    @cached_property
    def _ep_match_cache(self) -> dict[tuple[str, str, str], bool]:
        """Disk-backed memo for ``EasyPrivacyMatcher.match(url, doc_url, type)``.

        Loaded once, lazily, from ``<cache_dir>/ep_match_cache.<fingerprint>.pkl``
        if present and fingerprint-matched; otherwise starts empty. Persisted by
        :meth:`_persist_ep_match_cache` once ``cookies`` finishes building (see
        ``FrameAccess.cookies``) so the next run — or the next plot script in
        the same session — starts warm instead of recomputing from scratch.
        """
        if self.cache_dir:
            loaded = ep_cache.load(self.cache_dir, self._ep_match_fingerprint)
            if loaded is not None:
                print(
                    f"[CookieDataset] loaded {len(loaded):,} cached EasyPrivacy "
                    f"match verdicts from disk"
                )
                return loaded
        return {}

    def _persist_ep_match_cache(self) -> None:
        """Flush ``_ep_match_cache`` to disk if it grew during this run.

        Best-effort: cache persistence must never break the analysis, so any
        I/O error is swallowed (the in-memory memo still works for the rest of
        this process either way).
        """
        if not (self.cache_dir and self._ep_match_cache_dirty):
            return
        try:
            ep_cache.save(
                self.cache_dir, self._ep_match_fingerprint, self._ep_match_cache
            )
            self._ep_match_cache_dirty = False
            print(
                f"[CookieDataset] persisted {len(self._ep_match_cache):,} "
                f"EasyPrivacy match verdicts to disk"
            )
        except Exception:
            pass

    def _ep_data_for_site(self, site: "SiteRaw") -> tuple[frozenset[str], int, float]:
        """Return (matched_url_set, count, pct) of EasyPrivacy-matched requests.

        Thin, instance-state-aware wrapper over the shared
        :func:`analysis.src.ep_matching.ep_data_for_site` (see that module's
        docstring for *why* the actual logic lives there rather than here: it
        must be byte-for-byte identical to what the parallel-prefetch workers
        run, or the two paths could silently diverge). This wrapper just owns
        the per-site result cache (``_ep_cache``, avoiding double computation
        when both ``_build_cookies`` and ``_build_sites`` call this) and flips
        ``_ep_match_cache_dirty`` when the shared verdict memo grows, so
        :meth:`_persist_ep_match_cache` knows to flush it to disk.
        """
        if site.path in self._ep_cache:
            return self._ep_cache[site.path]

        before = len(self._ep_match_cache)
        result = ep_matching.ep_data_for_site(
            site, self._ep_matcher, self._ep_match_cache
        )
        if len(self._ep_match_cache) > before:
            self._ep_match_cache_dirty = True

        self._ep_cache[site.path] = result
        return result

    def _prefetch_ep_data_parallel(self, sites: list["SiteRaw"]) -> None:
        needing = [s for s in sites if s.path not in self._ep_cache]
        if not needing:
            return
        n = self.n_workers or 0
        if n <= 1 or len(needing) < max(n * 2, 8):
            return  # too little work to be worth spinning up a pool

        by_domain: dict[str, list["SiteRaw"]] = {}
        for s in needing:
            by_domain.setdefault(s.domain, []).append(s)
        groups = sorted(by_domain.values(), key=len, reverse=True)

        batches: list[list[str]] = [[] for _ in range(n)]
        for i, group in enumerate(groups):
            batches[i % n].extend(str(s.path) for s in group)
        batches = [b for b in batches if b]
        if len(batches) <= 1:
            return

        from concurrent.futures import ProcessPoolExecutor, as_completed

        seed = dict(self._ep_match_cache)
        print(
            f"[CookieDataset] pre-fetching EasyPrivacy match data for "
            f"{len(needing):,} sites across {len(batches)} worker process(es)"
            + (f" (seeding each from {len(seed):,} cached verdicts)" if seed else "")
            + "…"
        )
        tracker_list_names = sorted(d.name for d in self.tracker_lists)
        n_done = 0
        with ProcessPoolExecutor(max_workers=len(batches)) as pool:
            futures = [
                pool.submit(
                    _ep_prefetch_worker,
                    batch,
                    self.data_dir,
                    tracker_list_names,
                    self.tracker_cache_dir,
                    seed,
                )
                for batch in batches
            ]
            for fut in as_completed(futures):
                ep_results, match_additions = fut.result()
                for path_str, result in ep_results.items():
                    self._ep_cache[Path(path_str)] = result
                if match_additions:
                    self._ep_match_cache.update(match_additions)
                    self._ep_match_cache_dirty = True
                n_done += 1
                print(
                    f"[CookieDataset]   worker {n_done}/{len(batches)} done "
                    f"(+{len(ep_results):,} sites, "
                    f"+{len(match_additions):,} new match verdicts)"
                )

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
