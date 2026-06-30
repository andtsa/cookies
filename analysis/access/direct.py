from __future__ import annotations

from functools import cached_property
from pathlib import Path

from client.trackers import TrackerList
from client.trackers.name_similarity import cluster_names

from ..src import ep_cache, ep_matching
from ..src.loading import load_site, load_site_lists, site_paths
from ..src.progress import bar, track
from ..src.records import SiteRaw

# Per-worker-process global, populated exactly once by `_ep_pool_init` (the
# pool's `initializer=`) rather than rebuilt on every task. Building an
# EasyPrivacyMatcher means parsing ~56k filter-list rules and compiling ~3.5k
# regexes — too expensive to redo per chunk, but it only needs to happen once
# per *process* (worker processes are reused across many chunk submissions).
_worker_matcher = None


def _site_rank(site: SiteRaw) -> int | None:
    """Authoritative rank for a site, read from ``crawl_context.rank``.

    The crawler embeds the site's line number in the ranking list here (verified
    to match ``list_websites_1M.csv`` exactly), so it is the trusted source for
    rank-capping — no need to re-derive from the CSV. Returns ``None`` when a
    site carries no rank.
    """
    ctx = site.data.get("crawl_context") or {}
    r = ctx.get("rank")
    return int(r) if r is not None else None


def _ep_pool_init(
    tracker_cache_dir: str,
    tracker_list_names: list[str],
    engine: str = "hyperscan",
    cache_dir: str | None = None,
    ruleset_key: str | None = None,
) -> None:
    """``ProcessPoolExecutor`` initializer: build this process's matcher once.

    Runs a single time when each worker process starts, before it accepts any
    chunks. The resulting :class:`EasyPrivacyMatcher` — including its internal
    candidate-cache, the part profiling shows actually dominates ``match()``
    cost (see the matcher's docstring) — then lives for the lifetime of the
    process and is reused across every chunk that process handles. With the
    ``hyperscan`` engine the per-process compile is amortised further by the
    serialised-DB cache (keyed by ``ruleset_key``): workers ``loadb`` a prebuilt
    database instead of recompiling ~50k patterns each.
    """
    global _worker_matcher
    from client.trackers import Detections, TrackerList
    from client.trackers.matcher import EasyPrivacyMatcher

    tl = TrackerList()
    tl.load(
        cache_dir=tracker_cache_dir,
        trackers={Detections[name] for name in tracker_list_names},
    )
    _worker_matcher = EasyPrivacyMatcher(
        tl._easyprivacy, engine, cache_dir=cache_dir, ruleset_key=ruleset_key
    )


def _ep_prefetch_chunk(
    path_strs: list[str],
    data_dir: str,
) -> tuple[dict[str, "ep_matching.EpResult"], dict["ep_matching.MatchKey", bool]]:
    assert _worker_matcher is not None, "pool initializer did not run"
    local_match_cache: dict[ep_matching.MatchKey, bool] = {}
    ep_results: dict[str, "ep_matching.EpResult"] = {}

    try:
        for path_str in path_strs:
            path = Path(path_str)
            site = load_site(path, data_dir)
            if site is None:
                continue
            ep_results[path_str] = ep_matching.ep_data_for_site(
                site, _worker_matcher, local_match_cache
            )
    except KeyboardInterrupt:
        pass

    return ep_results, local_match_cache


class RawAccess:
    # ------------------------------------------------------------------ raw
    @cached_property
    def _site_files(self) -> list[Path]:
        return site_paths(self.data_dir)

    def site_files(self) -> list[Path]:
        return self._site_files

    @cached_property
    def _raw_sites(self) -> list[SiteRaw]:
        paths = self.site_files()
        cap = getattr(self, "rank_cap", None)
        sites = []
        dropped = 0
        for path in track(paths, desc="load sites", total=len(paths), unit=" sites"):
            site = load_site(path, self.data_dir)
            if site is None:
                continue
            # Drop the ">cap" crawl overrun. Only sites with a *known* rank
            # exceeding the cap are removed; rank-less sites (e.g. non-ranked
            # crawls) are always kept.
            if cap is not None:
                rank = _site_rank(site)
                if rank is not None and rank > cap:
                    dropped += 1
                    continue
            sites.append(site)
        if cap is not None and dropped:
            print(
                f"[CookieDataset] rank-cap {cap:,}: kept {len(sites):,} sites, "
                f"dropped {dropped:,} ranked beyond the cap"
            )
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
        """EasyPrivacy request-URL matcher, built lazily from the tracker list.

        Uses ``self.engine`` (default ``hyperscan``, auto-falling back to ``re``)
        and reuses the serialised Hyperscan DB under ``cache_dir`` keyed by the
        EasyPrivacy ruleset fingerprint.
        """
        from client.trackers.matcher import EasyPrivacyMatcher

        return EasyPrivacyMatcher(
            self._tracker_list._easyprivacy,
            getattr(self, "engine", "hyperscan"),
            cache_dir=self.cache_dir,
            ruleset_key=self._ep_match_fingerprint,
        )

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
        """Consolidate ``_ep_match_cache`` to disk if it grew during this run.

        One full O(N) write that also drops the append-log (see
        :func:`ep_cache.save`). Use :meth:`_append_ep_match_cache` for the cheap
        incremental checkpoints during a long prefetch; call this once at the end.

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
                f"[CookieDataset] consolidated {len(self._ep_match_cache):,} "
                f"EasyPrivacy match verdicts to disk"
            )
        except Exception:
            pass

    def _append_ep_match_cache(self, new_items: dict) -> None:
        """Append just-computed verdicts to the on-disk log — O(len(new_items)).

        Flat cost regardless of how big the in-memory memo has grown, so
        periodic checkpoints during prefetch don't degrade into the O(N²)
        whole-dict rewrite that consolidating every time would cause.
        """
        if not (self.cache_dir and new_items):
            return
        try:
            ep_cache.append(self.cache_dir, self._ep_match_fingerprint, new_items)
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

        # Resolve "free" hits directly from the warm on-disk verdict memo
        # before spinning up any pool. On a re-run this is the common case —
        # _ep_cache (per-site results) isn't persisted, so every site looks
        # "needing" again, but _ep_match_cache (per-URL verdicts) usually is
        # already warm from the previous run. Without this check, every
        # worker started from an empty local_match_cache and re-ran the
        # expensive regex matching for verdicts the parent already had —
        # burning CPU for nothing and re-persisting an unchanged memo on every
        # checkpoint. ep_data_from_cache does pure dict lookups and bails
        # (returns None) on the first genuine miss, so this pass is cheap.
        still_needing: list["SiteRaw"] = []
        for s in needing:
            cached = ep_matching.ep_data_from_cache(s, self._ep_match_cache)
            if cached is not None:
                self._ep_cache[s.path] = cached
            else:
                still_needing.append(s)
        if len(still_needing) < len(needing):
            print(
                f"[CookieDataset] {len(needing) - len(still_needing):,}/{len(needing):,} "
                f"sites resolved straight from the warm verdict memo "
                f"(no matching needed); {len(still_needing):,} remain"
            )
        needing = still_needing
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
            f"({len(chunks):,} chunks of <={chunk_size} sites - "
            f"bounded per-task memory, matcher built once per process)..."
        )
        tracker_list_names = sorted(d.name for d in self.tracker_lists)
        engine = getattr(self, "engine", "hyperscan")
        # Incremental, append-only checkpoints on a time interval: each writes
        # only the verdicts accumulated since the last one (flat cost), instead
        # of rewriting the whole — and ever-growing — memo every N verdicts
        # (which is O(N^2) over the run and tanks throughput on a slow disk).
        import time as _time

        pending: dict = {}
        last_checkpoint = _time.monotonic()
        CHECKPOINT_INTERVAL_S = 60.0
        progress = bar(desc="EasyPrivacy match", total=len(needing), unit=" sites")
        with ProcessPoolExecutor(
            max_workers=n,
            mp_context=ctx,
            initializer=_ep_pool_init,
            initargs=(
                self.tracker_cache_dir,
                tracker_list_names,
                engine,
                self.cache_dir,
                self._ep_match_fingerprint,
            ),
        ) as pool:
            futures = [
                pool.submit(_ep_prefetch_chunk, chunk, self.data_dir)
                for chunk in chunks
            ]
            try:
                for fut in as_completed(futures):
                    ep_results, match_additions = fut.result()
                    for path_str, result in ep_results.items():
                        self._ep_cache[Path(path_str)] = result
                    if match_additions:
                        self._ep_match_cache.update(match_additions)
                        pending.update(match_additions)
                        self._ep_match_cache_dirty = True
                    progress.update(len(ep_results))
                    progress.set_postfix_str(
                        f"{len(self._ep_match_cache):,} verdicts cached"
                    )

                    if pending and (
                        _time.monotonic() - last_checkpoint >= CHECKPOINT_INTERVAL_S
                    ):
                        self._append_ep_match_cache(pending)
                        pending = {}
                        last_checkpoint = _time.monotonic()

                if pending:
                    self._append_ep_match_cache(pending)
                    pending = {}
                progress.close()
                # One consolidation at the end folds the append-log into the snapshot.
                self._persist_ep_match_cache()
            except KeyboardInterrupt:
                # Shut down the pool and persist whatever progress was made so
                # far — including anything still sitting in the append-log
                # buffer that hasn't hit disk yet.
                print(
                    "\n[CookieDataset] Interrupted by user. Saving progress and shutting down"
                )
                pool.shutdown(wait=True)
                if pending:
                    self._append_ep_match_cache(pending)
                    pending = {}
                progress.close()
                self._persist_ep_match_cache()
                print(
                    f"[CookieDataset] Saved {len(self._ep_cache):,} sites and "
                    f"{len(self._ep_match_cache):,} match verdicts. Exiting."
                )
                raise

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
