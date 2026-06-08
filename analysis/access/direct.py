from __future__ import annotations

from functools import cached_property
from pathlib import Path

from client.trackers import TrackerList
from client.trackers.name_similarity import cluster_names

from ..src import ep_cache, ep_matching
from ..src.loading import load_site, load_site_lists, site_paths
from ..src.records import SiteRaw

# Per-worker-process global, populated exactly once by `_ep_pool_init` (the
# pool's `initializer=`) rather than rebuilt on every task. Building an
# EasyPrivacyMatcher means parsing ~56k filter-list rules and compiling ~3.5k
# regexes — too expensive to redo per chunk, but it only needs to happen once
# per *process* (worker processes are reused across many chunk submissions).
_worker_matcher = None


def _ep_pool_init(tracker_cache_dir: str, tracker_list_names: list[str]) -> None:
    """``ProcessPoolExecutor`` initializer: build this process's matcher once.

    Runs a single time when each worker process starts, before it accepts any
    chunks. The resulting :class:`EasyPrivacyMatcher` — including its internal
    candidate-cache, the part profiling shows actually dominates ``match()``
    cost (see the matcher's docstring) — then lives for the lifetime of the
    process and is reused across every chunk that process handles.
    """
    global _worker_matcher
    from client.trackers import Detections, TrackerList
    from client.trackers.matcher import EasyPrivacyMatcher

    tl = TrackerList()
    tl.load(
        cache_dir=tracker_cache_dir,
        trackers={Detections[name] for name in tracker_list_names},
    )
    _worker_matcher = EasyPrivacyMatcher(tl._easyprivacy)


def _ep_prefetch_chunk(
    path_strs: list[str],
    data_dir: str,
) -> tuple[dict[str, "ep_matching.EpResult"], dict["ep_matching.MatchKey", bool]]:
    assert _worker_matcher is not None, "pool initializer did not run"
    local_match_cache: dict[ep_matching.MatchKey, bool] = {}
    ep_results: dict[str, "ep_matching.EpResult"] = {}

    for path_str in path_strs:
        path = Path(path_str)
        site = load_site(path, data_dir)
        if site is None:
            continue
        ep_results[path_str] = ep_matching.ep_data_for_site(
            site, _worker_matcher, local_match_cache
        )

    return ep_results, local_match_cache


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

        flat: list[str] = [str(s.path) for group in groups for s in group]
        chunk_size = max(1, min(self.ep_chunk_size or 200, len(flat)))
        chunks = [flat[i : i + chunk_size] for i in range(0, len(flat), chunk_size)]
        if len(chunks) <= 1:
            return

        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor, as_completed

        # Force "spawn" rather than the platform default ("fork" on Linux).
        # By this point self._raw_sites has already loaded every site's full
        # parsed JSON into the parent's heap (often many GB at production
        # scale). A forked child shares that via copy-on-write at first, but
        # CPython bumps refcounts on every object it touches, including while
        # just starting up / running GC over inherited structures, so those
        # pages get copied almost immediately, ballooning each child toward the
        # size of the *entire parent heap* before it does any real work. A
        # spawned child starts with a clean interpreter and only receives the
        # small, explicit arguments passed to submit()/initargs below.
        ctx = multiprocessing.get_context("spawn")

        print(
            f"[CookieDataset] pre-fetching EasyPrivacy match data for "
            f"{len(needing):,} sites across {n} worker process(es) "
            f"({len(chunks):,} chunks of ≤{chunk_size} sites — "
            f"bounded per-task memory, matcher built once per process)…"
        )
        tracker_list_names = sorted(d.name for d in self.tracker_lists)
        n_done = 0
        new_since_checkpoint = 0
        sites_since_log = 0
        CHECKPOINT_EVERY_NEW_VERDICTS = 50_000
        LOG_EVERY_SITES = max(chunk_size * 5, 1000)
        with ProcessPoolExecutor(
            max_workers=n,
            mp_context=ctx,
            initializer=_ep_pool_init,
            initargs=(self.tracker_cache_dir, tracker_list_names),
        ) as pool:
            futures = [
                pool.submit(_ep_prefetch_chunk, chunk, self.data_dir)
                for chunk in chunks
            ]
            for fut in as_completed(futures):
                ep_results, match_additions = fut.result()
                for path_str, result in ep_results.items():
                    self._ep_cache[Path(path_str)] = result
                if match_additions:
                    self._ep_match_cache.update(match_additions)
                    self._ep_match_cache_dirty = True
                    new_since_checkpoint += len(match_additions)
                n_done += 1
                sites_since_log += len(ep_results)

                if sites_since_log >= LOG_EVERY_SITES or n_done == len(chunks):
                    print(
                        f"[CookieDataset]   {n_done:,}/{len(chunks):,} chunks done "
                        f"({len(self._ep_cache):,}/{len(needing):,} sites total, "
                        f"{len(self._ep_match_cache):,} cached match verdicts)"
                    )
                    sites_since_log = 0

                if new_since_checkpoint >= CHECKPOINT_EVERY_NEW_VERDICTS:
                    self._persist_ep_match_cache()
                    new_since_checkpoint = 0

            self._persist_ep_match_cache()  # final checkpoint for the remainder

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
