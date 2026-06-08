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
        ep_chunk_size: int | None = None,
        engine: str = "hyperscan",
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
        self.n_workers = n_workers
        self.ep_chunk_size = ep_chunk_size
        # Matching engine for EasyPrivacy request matching: "hyperscan" (fast,
        # Linux/x86_64; auto-falls back to "re" when the extension is absent) or
        # "re" (stdlib reference). Deliberately *not* part of the cookies cache
        # fingerprint: the two engines are validated to produce identical
        # verdicts (tests/test_matcher_parity.py), so switching engines must not
        # invalidate the on-disk frame cache.
        self.engine = engine
        self._cache: dict[tuple, object] = {}
        self._ep_cache: dict = {}
        self._ep_match_cache_dirty = False
