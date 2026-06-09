"""
analysis
--------
Centralised cookie-analysis package: a single :class:`CookieDataset` that reads
the crawl output under ``cookies_data/`` and exposes it in both raw and analysed
form, with lazy computation and an on-disk cache keyed on the data-dir state.

Typical use::

    from analysis import CookieDataset
    ds = CookieDataset("cookies_data")
    ds.cookies                      # lean, cacheable per-cookie DataFrame
    ds.classified_cookies           # + tiered "looks like a tracker" label
    ds.sites                        # per-site DataFrame
    ds.group(by=["country"], metric="mean:is_tracker")
    ds.filter(country="Netherlands", is_tracker=True)
    ds.shared(); ds.syncing(); ds.cross_domain_reads()

Plots should consume :attr:`CookieDataset.cookies` / :attr:`.classified_cookies`
(directly, or via :meth:`.filter` / :meth:`.group`) rather than maintaining
their own loading & enrichment logic — this package is the single source of
truth for "what does the crawl data look like, enriched and ready to plot".

This module — :class:`CookieDataset`, :class:`SiteRaw`, and the lifetime-bucket
plot helpers — *is* the supported public surface. Everything that backs it
(path/context loading, enrichment rules, the tracker classifier, sharing /
syncing / cross-domain-read analyses, the on-disk cache) lives in
``analysis.src`` and is intentionally not exported: it's implementation detail
that's free to change shape, and reaching into it directly is the thing to
avoid. If a plot needs something ``analysis.src`` has but ``CookieDataset``
doesn't expose, that's a sign the public surface should grow — not that the
plot should import ``analysis.src.*``.
"""

from .dataset import CookieDataset
from .src.helpers import BUCKETS, BUCKET_COLORS, lifetime_bucket
from .src.records import SiteRaw

__all__ = [
    "CookieDataset",
    "SiteRaw",
    "BUCKETS",
    "BUCKET_COLORS",
    "lifetime_bucket",
]
