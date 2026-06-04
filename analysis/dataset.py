"""
analysis/dataset.py
-------------------
``CookieDataset`` — the single entry point for reading and analysing the crawl
output under ``cookies_data/``.

Everything is lazy: the constructor only stores config. The first access to
:attr:`cookies` parses every site JSON once, enriches it (party type, tracker
detection, entropy/md5, name family, lifetime bucket, setter/registered domains,
country/browser/category/rank context) and memoises the result — optionally
persisting it to a parquet cache keyed on the data-dir fingerprint so later runs
load in well under a second while files are unchanged.

The enriched ``cookies`` frame is the canonical source of truth. Object-style
lookups (``find_by_*``) and the analysis registry are projections over it, so a
derived value is never computed in two places.
"""

from __future__ import annotations

from functools import cached_property
from pathlib import Path

import pandas as pd

from client.trackers import Detections, TrackerList
from client.trackers.entropy import entropy_metrics
from client.trackers.js import build_cookie_domain_index, find_cross_domain_cookies
from client.trackers.name_similarity import cluster_names

from . import cache, sharing, syncing
from .enrich import (
    HIGH_ENTROPY_BITS,
    lifetime_bucket,
    md5_value,
    party_type,
    registered_domain,
)
from .loading import load_site, load_site_lists, site_paths
from .records import CookieRecord, SiteRaw

# Popularity tiers for rank-based plots (top of list = most popular).
RANK_TIERS = [
    (10, "Top 10"),
    (50, "Top 50"),
    (100, "Top 100"),
    (1_000, "101–1k"),
    (10_000, "1k–10k"),
    (100_000, "10k–100k"),
    (1_000_000, "100k–1M"),
]

# Registry of named analyses. Populated by @register (see analysis/analyses.py).
_REGISTRY: dict[str, callable] = {}


def register(name: str):
    """Decorator registering ``fn(dataset, **params) -> Any`` under ``name``."""

    def deco(fn):
        _REGISTRY[name] = fn
        return fn

    return deco


def _rank_tier(rank) -> str:
    if rank is None or pd.isna(rank) or rank <= 0:
        return "unknown"
    for ceiling, label in RANK_TIERS:
        if rank <= ceiling:
            return label
    return "100k–1M"


class CookieDataset:
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
        cluster_max_edit_distance: int = 2,
        cache_dir: str | None = ".analysis_cache",
        rebuild: bool = False,
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
                "popular": "list_websites_500.csv",
            }
        )
        self.recompute_trackers = recompute_trackers
        self.high_entropy_bits = high_entropy_bits
        self.sync_min_bits = sync_min_bits
        self.cluster_max_edit_distance = cluster_max_edit_distance
        self.cache_dir = cache_dir
        self.rebuild = rebuild
        # Memoisation store for parameterised methods / registry results.
        self._cache: dict[tuple, object] = {}

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

    def iter_sites(self):
        yield from self._raw_sites

    def iter_cookies(self):
        for site in self._raw_sites:
            for cookie in site.cookies:
                yield site, cookie

    def iter_requests(self):
        for site in self._raw_sites:
            for req in site.requests:
                yield site, req

    def iter_js_activity(self):
        for site in self._raw_sites:
            yield site, site.js_activity

    def site(
        self, domain: str, country: str | None = None, browser: str | None = None
    ) -> SiteRaw | None:
        for s in self._raw_sites:
            if s.domain != domain:
                continue
            if country is not None and s.country != country:
                continue
            if browser is not None and s.browser != browser:
                continue
            return s
        return None

    # -------------------------------------------------------------- helpers
    @cached_property
    def _tracker_list(self) -> TrackerList:
        tl = TrackerList()
        tl.load(cache_dir=self.tracker_cache_dir, trackers=self.tracker_lists)
        return tl

    @cached_property
    def _site_list_map(self) -> dict[str, tuple[str, int]]:
        return load_site_lists(self.site_lists)

    @cached_property
    def name_families(self) -> dict[str, str]:
        names = {c.get("name", "") for _, c in self.iter_cookies() if c.get("name")}
        return cluster_names(names, max_edit_distance=self.cluster_max_edit_distance)

    def _tracker_fields(self, cookie: dict) -> tuple[bool, list[str], str | None]:
        """Return ``(is_tracker, lists, matched_domain)`` for a cookie.

        Prefers the crawler-stored ``cookie["tracker"]`` block; recomputes via
        the tracker lists only when missing or ``recompute_trackers`` is set.
        """
        stored = cookie.get("tracker")
        if stored and not self.recompute_trackers:
            lists = stored.get("lists") or []
            return bool(lists), list(lists), stored.get("matched_domain")
        det = self._tracker_list.is_tracker(cookie)
        if det is None:
            return False, [], None
        return bool(det.lists), list(det.lists), det.matched_domain

    # --------------------------------------------------------- canonical frames
    @cached_property
    def _config_repr(self) -> str:
        return repr(
            (
                sorted(d.name for d in self.tracker_lists),
                self.recompute_trackers,
                self.high_entropy_bits,
                self.cluster_max_edit_distance,
                sorted(self.site_lists.items()),
            )
        )

    @cached_property
    def cookies(self) -> pd.DataFrame:
        if self.cache_dir and not self.rebuild:
            key = cache.dir_fingerprint(self.site_files(), self._config_repr)
            cached = cache.load(self.cache_dir, key)
            if cached is not None:
                self._sites_frame = cached[1]
                return cached[0]

        cookies_df = self._build_cookies()
        sites_df = self._build_sites(cookies_df)
        self._sites_frame = sites_df

        if self.cache_dir:
            key = cache.dir_fingerprint(self.site_files(), self._config_repr)
            cache.save(
                self.cache_dir,
                key,
                cookies_df,
                sites_df,
                meta={
                    "data_dir": self.data_dir,
                    "n_sites": len(self._raw_sites),
                    "n_cookies": int(len(cookies_df)),
                },
            )
        return cookies_df

    @cached_property
    def sites(self) -> pd.DataFrame:
        # Triggers the cookies build (which sets _sites_frame) if needed.
        _ = self.cookies
        return self._sites_frame

    def _build_cookies(self) -> pd.DataFrame:
        families = self.name_families
        rows: list[dict] = []
        for site in self._raw_sites:
            target_url = site.target_url
            site_domain = registered_domain(target_url)
            target_host = target_url.split("//")[-1].split("/")[0]
            category, rank = self._site_list_map.get(site_domain, ("unknown", None))
            for c in site.cookies:
                name = c.get("name", "")
                value = c.get("value", "") or ""
                source = c.get("source") or {}
                http = source.get("http") or {}
                metrics = entropy_metrics(value)
                is_tracker, lists, provider = self._tracker_fields(c)
                ctype = c.get("cookie_type", "session")
                is_session = ctype == "session"
                rows.append(
                    {
                        # context
                        "country": site.country,
                        "browser": site.browser,
                        "category": category,
                        "rank": rank,
                        "rank_tier": _rank_tier(rank),
                        "domain": site.domain,
                        "source_file": str(site.path),
                        "target_url": target_url,
                        "registered_domain": site_domain,
                        # raw cookie
                        "name": name,
                        "value": value,
                        "cookie_domain": c.get("domain", ""),
                        "cookie_type": ctype,
                        "session": is_session,
                        "secure": c.get("secure", False),
                        "http_only": c.get("http_only", False),
                        "same_site": c.get("same_site"),
                        "expires_at": c.get("expires_at"),
                        "lifetime_days": c.get("lifetime_days"),
                        # derived: party / source
                        "party_type": party_type(target_host, c.get("domain", "")),
                        "set_by_type": source.get("type"),
                        "setter_url": http.get("url"),
                        "set_by_initiator": http.get("initiator"),
                        "set_by_third_party": http.get("third_party"),
                        "set_by_ep_matched": http.get("easyprivacy_matched", False),
                        "setter_domain": registered_domain(http.get("url", "")) or None,
                        # derived: entropy / identity
                        "entropy": metrics["entropy"],
                        "total_bits": metrics["total_bits"],
                        "value_length": metrics["value_length"],
                        "md5_value": md5_value(value),
                        # derived: tracker
                        "is_tracker": is_tracker,
                        "is_tracker_ep": "EasyPrivacy" in lists,
                        "is_tracker_ocd": "OpenCookieDB" in lists,
                        "tracker_lists": lists,
                        "tracker_provider": provider,
                        # derived: lifetime / clustering / tld
                        "lifetime_bucket": lifetime_bucket(
                            c.get("lifetime_days"), is_session
                        ),
                        "name_family": families.get(name, name),
                        "tld": (
                            registered_domain(c.get("domain", "")).rsplit(".", 1)[-1]
                            if c.get("domain")
                            else ""
                        ),
                    }
                )
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        # Legacy aliases so unmigrated plot scripts read the frame unchanged.
        df["httpOnly"] = df["http_only"]
        df["sameSite"] = df["same_site"]
        df["is_tracker_bool"] = df["is_tracker"]
        df["bucket"] = df["lifetime_bucket"]
        return df

    def _build_sites(self, cookies_df: pd.DataFrame) -> pd.DataFrame:
        rows = []
        cookies_by_site = (
            {k: v for k, v in cookies_df.groupby(["country", "browser", "domain"])}
            if not cookies_df.empty
            else {}
        )
        for site in self._raw_sites:
            summary = site.data.get("summary", {}) or {}
            sc = summary.get("cookies", {}) or {}
            sr = summary.get("requests", {}) or {}
            sj = summary.get("js", {}) or {}
            target_url = site.target_url
            sub = cookies_by_site.get((site.country, site.browser, site.domain))
            persistent = (
                sub[~sub["session"]] if sub is not None and not sub.empty else None
            )
            category, rank = self._site_list_map.get(
                registered_domain(target_url), ("unknown", None)
            )
            rows.append(
                {
                    "country": site.country,
                    "browser": site.browser,
                    "category": category,
                    "rank": rank,
                    "rank_tier": _rank_tier(rank),
                    "domain": site.domain,
                    "target_url": target_url,
                    "registered_domain": registered_domain(target_url),
                    "total_cookies": sc.get("total", 0),
                    "num_session": sc.get("session", 0),
                    "num_persistent": sc.get("persistent", 0),
                    "num_trackers": sc.get("trackers", 0),
                    "tracker_pct": sc.get("tracker_pct", 0.0),
                    "total_requests": sr.get("total", 0),
                    "easyprivacy_requests": sr.get("easyprivacy", 0),
                    "easyprivacy_pct": sr.get("easyprivacy_pct", 0.0),
                    "js_reads": sj.get("reads", 0),
                    "js_writes": sj.get("writes", 0),
                    "avg_lifetime_days": (
                        float(persistent["lifetime_days"].mean())
                        if persistent is not None and not persistent.empty
                        else 0.0
                    ),
                    "median_lifetime_days": (
                        float(persistent["lifetime_days"].median())
                        if persistent is not None and not persistent.empty
                        else 0.0
                    ),
                    "max_lifetime_days": (
                        float(persistent["lifetime_days"].max())
                        if persistent is not None and not persistent.empty
                        else 0.0
                    ),
                }
            )
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ lookups
    def _filter(self, df: pd.DataFrame, country=None, browser=None) -> pd.DataFrame:
        if country is not None:
            df = df[df["country"] == country]
        if browser is not None:
            df = df[df["browser"] == browser]
        return df

    def find_by_name(self, name: str, *, country=None, browser=None) -> pd.DataFrame:
        df = self.cookies
        return self._filter(df[df["name"] == name], country, browser)

    def find_by_family(
        self, family_or_name: str, *, country=None, browser=None
    ) -> pd.DataFrame:
        family = self.name_families.get(family_or_name, family_or_name)
        df = self.cookies
        return self._filter(df[df["name_family"] == family], country, browser)

    def find_by_domain(
        self, registered_domain: str, *, country=None, browser=None
    ) -> pd.DataFrame:
        df = self.cookies
        return self._filter(
            df[df["registered_domain"] == registered_domain], country, browser
        )

    def find_by_setter(
        self, setter_domain: str, *, country=None, browser=None
    ) -> pd.DataFrame:
        df = self.cookies
        return self._filter(df[df["setter_domain"] == setter_domain], country, browser)

    def filter(self, **conditions) -> pd.DataFrame:
        """Return rows of ``cookies`` matching every ``column=value`` pair."""
        df = self.cookies
        for col, val in conditions.items():
            df = df[df[col] == val]
        return df

    def group(
        self,
        by: list[str],
        metric: str = "count",
        *,
        trackers_only: bool = False,
        df: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Generic group-by reduction most tabular plots reduce to.

        ``metric`` is ``"count"``, ``"nunique:<col>"`` or ``"<agg>:<col>"`` where
        ``<agg>`` is any pandas aggregation (``mean``, ``sum``, ``median`` …).
        Returns a tidy frame with ``by`` columns plus a ``value`` column.
        """
        frame = self.cookies if df is None else df
        if trackers_only:
            frame = frame[frame["is_tracker"]]
        grouped = frame.groupby(by, dropna=False)
        if metric == "count":
            out = grouped.size().reset_index(name="value")
        elif metric.startswith("nunique:"):
            col = metric.split(":", 1)[1]
            out = grouped[col].nunique().reset_index(name="value")
        else:
            agg, col = metric.split(":", 1)
            out = grouped[col].agg(agg).reset_index(name="value")
        return out

    def cookie_records(self, df: pd.DataFrame | None = None) -> list[CookieRecord]:
        frame = self.cookies if df is None else df
        out = []
        for r in frame.to_dict("records"):
            out.append(
                CookieRecord(
                    country=r["country"],
                    browser=r["browser"],
                    category=r["category"],
                    registered_domain=r["registered_domain"],
                    name=r["name"],
                    name_family=r["name_family"],
                    value=r["value"],
                    md5_value=r["md5_value"],
                    cookie_type=r["cookie_type"],
                    party_type=r["party_type"],
                    is_tracker=bool(r["is_tracker"]),
                    tracker_provider=r["tracker_provider"],
                    total_bits=r["total_bits"],
                    lifetime_days=r["lifetime_days"],
                    lifetime_bucket=r["lifetime_bucket"],
                    setter_domain=r["setter_domain"],
                    raw=r,
                )
            )
        return out

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

    # ----------------------------------------------------------------- registry
    def analysis(self, name: str, **params):
        """Run a registered analysis by name (memoised on ``(name, params)``)."""
        if name not in _REGISTRY:
            raise KeyError(f"Unknown analysis {name!r}. Available: {sorted(_REGISTRY)}")
        ckey = ("analysis", name, tuple(sorted(params.items())))
        if ckey not in self._cache:
            self._cache[ckey] = _REGISTRY[name](self, **params)
        return self._cache[ckey]

    @staticmethod
    def available_analyses() -> list[str]:
        return sorted(_REGISTRY)
