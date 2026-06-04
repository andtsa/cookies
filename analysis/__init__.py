"""
analysis
--------
Centralised cookie-analysis package: a single :class:`CookieDataset` that reads
the crawl output under ``cookies_data/`` and exposes it in both raw and analysed
form, with lazy computation and an on-disk cache keyed on the data-dir state.

Typical use::

    from analysis import CookieDataset
    ds = CookieDataset("cookies_data")
    ds.cookies                      # enriched per-cookie DataFrame (canonical)
    ds.sites                        # per-site DataFrame
    ds.find_by_family("_ga")        # all cookies in the _ga name family
    ds.analysis("trackers_by_country")
    ds.shared(); ds.syncing(); ds.cross_domain_reads()

Add a new analysis with the :func:`register` decorator (see analysis/analyses.py).
"""

from .dataset import CookieDataset, register
from .records import CookieRecord, SiteRaw

# Importing the built-ins populates the analysis registry.
from . import analyses  # noqa: E402,F401

__all__ = ["CookieDataset", "register", "CookieRecord", "SiteRaw"]
