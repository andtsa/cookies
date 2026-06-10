#!/usr/bin/env python
"""
Warm the annotation cache for a crawl directory.

Builds (and persists to ``--cache-dir``) everything the plot scripts need so
that they no longer recompute the expensive annotation on every run:

  * the enriched ``cookies`` / ``sites`` frames + the EasyPrivacy verdict memo
    (via :attr:`CookieDataset.cookies`), and
  * the tiered tracker labels + their three relational artifacts
    (``shared_groups`` / ``sync_events`` / ``cross_domain_reads``) via
    :attr:`CookieDataset.classified_cookies`.

This decouples *annotation* from *plotting*: run this once after a crawl (or
after refreshing the tracker lists), then every plot script loads the labels
straight from disk.

Usage::

    python scripts/annotate.py --data ./cookies_data \
        --cache-dir .analysis_cache --workers 8 --engine hyperscan

``--engine hyperscan`` (default) uses the multi-pattern Hyperscan database on
Linux/x86_64 and transparently falls back to the stdlib ``re`` engine where the
extension is unavailable (e.g. a Windows dev box).
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# Make the repo-root ``analysis`` package importable from scripts/.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analysis import CookieDataset  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", default="./cookies_data", help="crawl data directory")
    p.add_argument(
        "--cache-dir",
        default=".analysis_cache",
        help="where to read/write the warmed caches",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=(os.cpu_count() or 8) // 2,
        help="parallel worker processes for EasyPrivacy prefetch",
    )
    p.add_argument(
        "--engine",
        default="hyperscan",
        choices=["hyperscan", "re"],
        help="matching engine (hyperscan auto-falls back to re if unavailable)",
    )
    p.add_argument(
        "--rebuild",
        action="store_true",
        help="ignore existing caches and recompute from scratch",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    ds = CookieDataset(
        args.data,
        cache_dir=args.cache_dir,
        n_workers=args.workers,
        rebuild=args.rebuild,
        engine=args.engine,
    )

    t0 = time.time()
    print(f"[annotate] warming base frames for {args.data!r} ...")
    cookies = ds.cookies  # frames + EP verdict memo (+ serialised HS db)
    sites = ds.sites
    print(
        f"[annotate]   {len(cookies):,} cookies across {len(sites):,} site rows "
        f"(active EP engine: {_active_engine(ds)})"
    )

    print("[annotate] warming annotation (labels + relational artifacts) ...")
    classified = ds.classified_cookies

    print("[annotate] warming sync-subtype + third-party-read tables ...")
    subtype_rows = ds.sync_subtype_rows()
    tp_reads = ds.third_party_reads()
    print(
        f"[annotate]   {len(subtype_rows):,} sync rows, "
        f"{len(tp_reads):,} third-party read rows"
    )

    elapsed = time.time() - t0

    tiers = (
        classified["tracker_tier"]
        .value_counts()
        .reindex(["confirmed", "probable", "possible", "none"], fill_value=0)
    )
    print(f"[annotate] done in {elapsed:,.1f}s. Tier distribution:")
    for tier, count in tiers.items():
        print(f"[annotate]   {tier:>9}: {count:,}")
    print(f"[annotate] caches written under {args.cache_dir!r}")
    return 0


def _active_engine(ds: CookieDataset) -> str:
    """Report the engine the matcher resolved to, without forcing a build.

    ``_ep_matcher`` is a ``cached_property``; if a crawl is fully pre-annotated
    it is never built, and we must not build it here just to print a name.
    """
    matcher = ds.__dict__.get("_ep_matcher")
    if matcher is not None:
        return matcher.engine_name
    return f"{getattr(ds, 'engine', 'unknown')} (not built; pre-annotated crawl)"


if __name__ == "__main__":
    raise SystemExit(main())
