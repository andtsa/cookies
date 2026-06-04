"""
analysis/loading.py
-------------------
Filesystem walking, path-context decoding, and the website-list join.

Crawler output layout is ``{data_dir}/{country}/{browser}/{hexprefix}/{slug}.json``
(e.g. ``cookies_data/Netherlands/chromium/3e/pinterest_com.json``). An older
pre-country layout ``{data_dir}/{browser}/{hexprefix}/{slug}.json`` is tolerated
(country becomes ``"unknown"``).

Rank and category are NOT in the crawler JSON (see the plan's "crawler gaps"):
they are recovered here by joining each site's registrable domain against the
website-list CSVs (``rank,url``). This join is the temporary stand-in until the
crawler records rank/category directly.
"""

from __future__ import annotations

import csv
import glob
import json
import os
from pathlib import Path

from .enrich import registered_domain
from .records import SiteRaw

# Known Playwright engines (client/config.py Browser enum). Used to recognise a
# pre-country layout where the first path component is already a browser.
BROWSERS = {"chromium", "firefox", "webkit"}


def site_paths(data_dir: str | os.PathLike) -> list[Path]:
    """All site JSON files under ``data_dir`` (recursive, sorted)."""
    pattern = os.path.join(str(data_dir), "**", "*.json")
    return [Path(p) for p in sorted(glob.glob(pattern, recursive=True))]


def path_context(path: Path, data_dir: str | os.PathLike) -> tuple[str, str, str]:
    """Decode ``(country, browser, domain_slug)`` from a site path.

    Falls back gracefully: a 3-component relative path (browser/hex/slug) yields
    ``country="unknown"``; anything shallower yields ``"unknown"`` for the
    missing levels.
    """
    rel = Path(path).relative_to(Path(data_dir))
    parts = rel.parts
    slug = Path(path).stem
    if len(parts) >= 4:
        country, browser = parts[0], parts[1]
    elif len(parts) == 3 and parts[0] in BROWSERS:
        country, browser = "unknown", parts[0]
    elif len(parts) == 3:
        country, browser = parts[0], parts[1]
    else:
        country = "unknown"
        browser = next((p for p in parts if p in BROWSERS), "unknown")
    return country, browser, slug


def load_site(path: Path, data_dir: str | os.PathLike) -> SiteRaw | None:
    """Read one site JSON into a :class:`SiteRaw` (None on parse failure)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
    country, browser, slug = path_context(path, data_dir)
    return SiteRaw(path=path, country=country, browser=browser, domain=slug, data=data)


def load_site_lists(site_lists: dict[str, str]) -> dict[str, tuple[str, int]]:
    """Build ``registered_domain -> (category, rank)`` from website-list CSVs.

    ``site_lists`` maps a category label to a ``rank,url`` CSV path. When a
    domain appears in several lists the *first* configured list wins (so callers
    put the more specific list, e.g. ``medical``, first). Missing files are
    skipped silently — the join just yields fewer matches.
    """
    mapping: dict[str, tuple[str, int]] = {}
    for category, csv_path in (site_lists or {}).items():
        if not csv_path or not os.path.exists(csv_path):
            continue
        with open(csv_path, encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                url = (row.get("url") or "").strip()
                if not url:
                    continue
                dom = registered_domain(url)
                if not dom or dom in mapping:
                    continue
                try:
                    rank = int(row.get("rank") or 0)
                except ValueError:
                    rank = 0
                mapping[dom] = (category, rank)
    return mapping
