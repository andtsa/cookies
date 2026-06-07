from __future__ import annotations

from client.trackers import Detections

from .access.aggregate import AggregateAccess
from .access.frames import FrameAccess
from .access.direct import RawAccess
from .access.relational import RelationalAccess
from .src.helpers import HIGH_ENTROPY_BITS


class CookieDataset(RawAccess, FrameAccess, AggregateAccess, RelationalAccess):
    def __init__(
        self,
        data_dir: str = "cookies_data",
        *,
        tracker_lists: set[Detections] | None = None,
        tracker_cache_dir: str = ".tracker_cache",
        site_lists: dict[str, str] | None = None,
        recompute_trackers: bool = False,
        high_entropy_bits: float = HIGH_ENTROPY_BITS,
        sync_min_bits: float = HIGH_ENTROPY_BITS,
        cluster_max_edit_distance: int = 0,
        cache_dir: str | None = ".analysis_cache",
        rebuild: bool = False,
        n_workers: int | None = None,
    ) -> None:
        self.data_dir = str(data_dir)
        self.tracker_lists = set(
            tracker_lists or {Detections.EasyPrivacy, Detections.OpenCookieDB}
        )
        self.tracker_cache_dir = tracker_cache_dir
        self.site_lists = (
            site_lists
            if site_lists is not None
            else {
                "medical": "list_websites_health.csv",
                "popular": "list_websites_1M.csv",
            }
        )
        self.recompute_trackers = recompute_trackers
        self.high_entropy_bits = high_entropy_bits
        self.sync_min_bits = sync_min_bits
        self.cluster_max_edit_distance = cluster_max_edit_distance
        self.cache_dir = cache_dir
        self.rebuild = rebuild
        # Opt-in: when >1, the expensive EasyPrivacy-matching prefetch (the
        # ~96%-of-runtime bottleneck on large crawls per profiling) is split
        # across this many worker processes before the normal single-threaded
        # build runs — see RawAccess._prefetch_ep_data_parallel. None/<=1
        # preserves the original sequential behaviour exactly (default — keeps
        # small/local crawls and tests free of pool start-up overhead).
        self.n_workers = n_workers
        self._cache: dict[tuple, object] = {}
        self._ep_cache: dict = {}
        # Pure-function memo for EasyPrivacyMatcher.match(url, doc_url, type).
        # The same tracker request (e.g. Google Analytics, DoubleClick, common
        # ad/CDN scripts) recurs across a large fraction of the 100k sites, and
        # — because this crawl is laid out as {country}/{browser}/{site} — the
        # *same* site is re-matched once per country×browser combination with
        # (typically) identical request/document URLs. Caching on the matcher's
        # actual inputs collapses both kinds of redundancy and turns the ~96%
        # of runtime spent in `_find_matching_rule`'s ~3.5k-regex generic-rule
        # scan into a dict lookup for every repeat. Safe: match() is a pure
        # function of these three values.
        #
        # Lazily loaded from / persisted to disk (see `_ep_match_cache` /
        # `_persist_ep_match_cache` in RawAccess) so a second run — or the next
        # plot script pointed at the same data — pays for each unique triple
        # exactly once, ever, not once per process.
        self._ep_match_cache_dirty = False
