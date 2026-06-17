from __future__ import annotations

from functools import cached_property

import pandas as pd

from client.trackers.entropy import entropy_metrics

from ..src import cache, classified_cache, classifier, ep_matching
from ..src.helpers import lifetime_bucket, md5_value, party_type, registered_domain
from ..src.progress import track

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


def _rank_tier(rank) -> str:
    if rank is None or pd.isna(rank) or rank <= 0:
        return "unknown"
    for ceiling, label in RANK_TIERS:
        if rank <= ceiling:
            return label
    return "100k–1M"


class FrameAccess:
    # canonical frames
    @cached_property
    def _config_repr(self) -> str:
        return repr(
            (
                sorted(d.name for d in self.tracker_lists),
                self.recompute_trackers,
                self.high_entropy_bits,
                self.cluster_max_edit_distance,
                sorted(self.site_lists.items()),
                self.rank_cap,
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

        try:
            cookies_df = self._build_cookies()
            sites_df = self._build_sites(cookies_df)
        except KeyboardInterrupt:
            print("\n[CookieDataset] Analysis interrupted by user.")
            self._persist_ep_match_cache()
            raise
        self._sites_frame = sites_df

        # Flush the EasyPrivacy match memo to disk if it grew this run — keyed
        # independently of the cookies/sites parquet cache (which only helps
        # when *nothing* changed). The memo helps even when individual site
        # files change, since it's keyed on request triples, not file state.
        self._persist_ep_match_cache()

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
        # Triggers the cookies build (which sets _sites_frame).
        _ = self.cookies
        return self._sites_frame

    @cached_property
    def classified_cookies(self) -> pd.DataFrame:
        """
        Adds three columns (see :mod:`analysis.src.classifier`):

        - ``tracker_tier``       ordered ``none < possible < probable < confirmed``
        - ``tracker_signals``    list[str] of every rule that fired (auditable)
        - ``is_tracker``         bool — ``tracker_tier >= "probable"`` (unified canonical
                                 definition, overrides the list-only bool in :attr:`cookies`)

        **This is the expensive view** — deliberately kept separate from
        :attr:`cookies` rather than merged in. Computing the label requires
        three additional full-dataset relational passes (:attr:`shared_groups`,
        :attr:`sync_events`, :meth:`cross_domain_reads`) plus a row-by-row
        classification, on top of everything ``cookies`` already costs. Folding
        it into ``cookies`` would mean *every* plot — including a trivial
        "first- vs third-party" count — pays for cookie-syncing detection and
        cross-site identifier matching across the whole dataset, every time.
        Reach for this only when a plot specifically needs the tiered label.

        (It also *can't* be folded into the disk-cached half of ``cookies``
        without circularity: the relational passes themselves read the
        per-cookie frame to do their work.)

        Like :attr:`cookies`, the labels + their three relational artifacts are
        persisted to disk (see :mod:`analysis.src.classified_cache`) so the next
        run — or the next plot script — loads them instead of recomputing. Only
        the label columns are stored; they are re-joined to ``cookies`` (already
        disk-cached) by position, sound because the key embeds the cookies
        fingerprint.
        """
        df = self.cookies
        if df.empty:
            return df.assign(
                tracker_tier=pd.Categorical(
                    [], categories=classifier.TIERS, ordered=True
                ),
                tracker_signals=pd.Series(dtype="object"),
                is_tracker=pd.Series(dtype="bool"),
            )

        key = self._classified_key()
        if self.cache_dir and not self.rebuild and key is not None:
            cached = classified_cache.load(self.cache_dir, key)
            if cached is not None:
                labels, artifacts = cached
                self._hydrate_relational(artifacts)
                labels.index = df.index
                result = pd.concat([df, labels], axis=1)
                result["is_tracker"] = result["tracker_tier"] >= "probable"
                return result

        labels = classifier.classify_cookies(
            df,
            shared_groups=self.shared_groups,
            sync_events=self.sync_events,
            cross_domain_reads=self.cross_domain_reads(),
            high_entropy_bits=self.high_entropy_bits,
        )

        if self.cache_dir and key is not None:
            classified_cache.save(
                self.cache_dir,
                key,
                labels,
                artifacts={
                    "shared_groups": self.shared_groups,
                    "sync_events": self.sync_events,
                    "cross_domain_reads": self.cross_domain_reads(),
                },
                meta={"data_dir": self.data_dir, "n_cookies": int(len(df))},
            )
        result = pd.concat([df, labels], axis=1)
        # Unified tracker boolean: True iff the classifier found at least one
        # strong, unambiguous signal (tier >= "probable").
        # This overrides the list-only bool that cookies carries under the same
        # name, so every frame consumer reads the same definition from the same
        # column — whether they got here via ds.classified_cookies directly, or
        # via group(trackers_only=True), or via load_cookie_data().
        result["is_tracker"] = result["tracker_tier"] >= "probable"
        return result

    def _classified_key(self) -> str | None:
        """Cache key for the annotation: the cookies fingerprint extended with
        the label-affecting config (``sync_min_bits``/``high_entropy_bits``)."""
        if not self.cache_dir:
            return None
        base_key = cache.dir_fingerprint(self.site_files(), self._config_repr)
        extra = repr((self.sync_min_bits, self.high_entropy_bits))
        return classified_cache.classified_fingerprint(base_key, extra)

    def _hydrate_relational(self, artifacts: dict) -> None:
        """Seed ``self._cache`` with loaded relational artifacts so later direct
        calls to ``shared``/``syncing``/``cross_domain_reads`` are also warm
        (keys must match :class:`RelationalAccess`' defaults)."""
        self._cache[("shared", "name-md5", 2, False, False)] = artifacts[
            "shared_groups"
        ]
        # Key must match RelationalAccess.syncing()'s default (deep=False, path=True).
        self._cache[("syncing", False, True)] = artifacts["sync_events"]
        self._cache[("cross_domain_reads", 2)] = artifacts["cross_domain_reads"]

    # ------------------------------------------------------------ row builders
    def _build_cookies(self) -> pd.DataFrame:
        families = self.name_families

        # Optional parallel prefetch of the expensive EasyPrivacy-matching step
        # (96% of runtime on the 100k-site crawl per profiling). No-op unless
        # n_workers > 1; when it runs, _ep_data_for_site below simply finds
        # _ep_cache/_ep_match_cache already warm and skips straight to the
        # cheap per-cookie row construction. See RawAccess._prefetch_ep_data_parallel.
        if self.n_workers and self.n_workers > 1:
            # needs_ep_data covers BOTH triggers of _ep_data_for_site — the
            # cookie-level one this loop uses below (need_ep) AND the
            # site-level one _build_sites uses for easyprivacy_requests/_pct.
            # Missing the latter here is exactly what leaves a straggler site
            # to cold-build its own _ep_matcher in the main process later.
            sites_needing_ep = [
                s for s in self._raw_sites if ep_matching.needs_ep_data(s)
            ]
            if sites_needing_ep:
                self._prefetch_ep_data_parallel(sites_needing_ep)

        rows: list[dict] = []
        for site in track(
            self._raw_sites,
            desc="build cookies",
            total=len(self._raw_sites),
            unit=" sites",
        ):
            target_url = site.target_url
            site_domain = registered_domain(target_url)
            target_host = target_url.split("//")[-1].split("/")[0]
            ctx = site.data.get("crawl_context") or {}
            country = ctx.get("country") or site.country
            browser = ctx.get("browser") or site.browser
            rank = ctx.get("rank")
            category = ctx.get("category") or "unknown"

            # Pre-fetch EP data only when at least one cookie in this site is
            # missing setter_ep_matched (i.e. new-format crawl file). When
            # n_workers prefetching ran above, this just reads the now-warm
            # _ep_cache instead of recomputing.
            cookies_list = site.cookies
            need_ep = ep_matching.needs_live_ep_matching(site)
            ep_urls: frozenset[str] = (
                self._ep_data_for_site(site)[0] if need_ep else frozenset()
            )

            for c in cookies_list:
                name = c.get("name", "")
                value = c.get("value", "") or ""
                setter_url = c.get("setter_url")
                metrics = entropy_metrics(value)
                is_tracker, lists, provider = self._tracker_fields(c)
                ctype = c.get("cookie_type", "session")
                is_session = ctype == "session"
                rows.append(
                    {
                        # context
                        "country": country,
                        "browser": browser,
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
                        "set_by_type": c.get("setter_type"),
                        "setter_url": setter_url,
                        "setter_frame_url": c.get("setter_frame_url"),
                        "setter_request_type": c.get("setter_request_type"),
                        "set_by_initiator": c.get("setter_initiator"),
                        "set_by_third_party": c.get("setter_third_party"),
                        "set_by_ep_matched": (
                            bool(c["setter_ep_matched"])
                            if "setter_ep_matched" in c
                            else bool(setter_url and setter_url in ep_urls)
                        ),
                        "setter_domain": registered_domain(setter_url or "") or None,
                        # derived: entropy / identity
                        "entropy": metrics["entropy"],
                        "total_bits": metrics["total_bits"],
                        "value_length": metrics["value_length"],
                        "md5_value": md5_value(value),
                        # derived: tracker (list-only; canonical is_tracker lives in classified_cookies)
                        "is_tracker_listed": is_tracker,
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
        df["is_tracker_bool"] = df["is_tracker_listed"]
        df["bucket"] = df["lifetime_bucket"]
        return df

    def _build_sites(self, cookies_df: pd.DataFrame) -> pd.DataFrame:
        rows = []
        cookies_by_site = (
            {k: v for k, v in cookies_df.groupby(["country", "browser", "domain"])}
            if not cookies_df.empty
            else {}
        )
        for site in track(
            self._raw_sites,
            desc="build sites",
            total=len(self._raw_sites),
            unit=" sites",
        ):
            ctx = site.data.get("crawl_context") or {}
            country = ctx.get("country") or site.country
            browser = ctx.get("browser") or site.browser
            rank = ctx.get("rank")
            category = ctx.get("category") or "unknown"
            summary = site.data.get("summary", {}) or {}
            sc = summary.get("cookies", {}) or {}
            sr = summary.get("requests", {}) or {}
            sj = summary.get("js", {}) or {}
            target_url = site.target_url
            # Key must match what _build_cookies used (both read from crawl_context).
            sub = cookies_by_site.get((country, browser, site.domain))
            persistent = (
                sub[~sub["session"]] if sub is not None and not sub.empty else None
            )
            rows.append(
                {
                    "country": country,
                    "browser": browser,
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
                    "easyprivacy_requests": (
                        sr["easyprivacy"]
                        if "easyprivacy" in sr
                        else self._ep_data_for_site(site)[1]
                    ),
                    "easyprivacy_pct": (
                        sr["easyprivacy_pct"]
                        if "easyprivacy_pct" in sr
                        else self._ep_data_for_site(site)[2]
                    ),
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
